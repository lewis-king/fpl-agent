// Isolated browser checks: fetch the read model once, then mock every API call.
// Never submits real transfers, authenticates, or launches a decision refresh.
import assert from 'node:assert/strict'
import { existsSync, readdirSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const origin = process.env.FPLAGENT_TEST_ORIGIN ?? 'http://127.0.0.1:5173'
const response = await fetch(`${origin}/api/v1/workspace`)
assert.ok(response.ok, 'Start the local API and frontend first')
const workspace = await response.json()
assert.equal(workspace.decision.weekly.status, 'ready', 'A validated weekly receipt is required')
const weekly = workspace.decision.weekly
const cache = join(homedir(), '.cache', 'ms-playwright')
const executablePath = process.env.CHROMIUM_EXECUTABLE_PATH ?? readdirSync(cache)
  .filter(name => /^chromium-\d+$/.test(name)).sort().reverse()
  .map(name => join(cache, name, 'chrome-linux64', 'chrome')).find(existsSync)
assert.ok(executablePath, 'A Playwright Chromium is required')
const browser = await chromium.launch({ executablePath, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
page.setDefaultTimeout(15000)
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname
  let body = {}
  if (path === '/api/v1/workspace') body = workspace
  else if (path === '/api/v1/integrations/fpl') body = { status: 'connected' }
  else if (path === '/api/v1/integrations/fpl/sync') body = { entry_id: workspace.user.fpl_entry_id, status: 'synced', manager_state_status: 'ready' }
  else if (path === '/api/v1/workspace/refresh') body = {
    schema_version: 'workspace-refresh-v1', run_id: 'mock-validated', status: 'published',
    mode: 'weekly', event: weekly.event, published: true, reused: false,
    started_at: weekly.created_at, completed_at: workspace.generated_at,
    completed_stages: [], completed_stage_count: 5, total_stages: 5,
    message: 'Validated test receipt.',
  }
  else if (path === '/api/v1/workspace/refresh/schedule') body = {
    schema_version: 'deadline-refresh-schedule-v1', status: 'covered', event: weekly.event,
    cadence_label: '6-hour cadence', message: 'Covered test window.',
    last_validated_at: workspace.generated_at,
  }
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
})

try {
  await page.goto(origin)
  const panel = page.locator('.weekly-decision')
  await panel.waitFor({ state: 'visible' })
  if (weekly.selected.route_type === 'roll') {
    await panel.locator('[aria-label="Hold decision context"]').waitFor()
    assert.equal(await panel.getByText('Simulation mean CI · 95%', { exact: true }).count(), 0)
    assert.equal(await panel.getByText('About these estimates', { exact: true }).count(), 0)
    await panel.getByText(weekly.explanation, { exact: true }).waitFor()
  } else {
    await panel.getByText('Simulation mean CI · 95%', { exact: true }).waitFor()
    await panel.getByText('About these estimates', { exact: true }).click()
    await panel.getByText('Simulation precision is not forecast certainty', { exact: true }).waitFor()
    assert.ok(await panel.getByText(/does not include all model error/).isVisible())
    if (weekly.objective_tradeoff) {
      assert.ok(await panel.getByText(/cross-model protection gives up another/).isVisible())
    }
  }
  assert.equal(await panel.getByText('Paired 95% range', { exact: true }).count(), 0)
  await panel.getByText('Chip & timing', { exact: true }).click()
  const statuses = panel.getByRole('list', { name: 'Chip evaluation status' })
  await statuses.waitFor()
  assert.equal(await statuses.getByRole('listitem').count(), weekly.chip_advice.candidate_statuses.length)
  assert.ok(await statuses.getByText('Research only · not validated', { exact: true }).count() >= 1)
  await statuses.getByRole('listitem').last().scrollIntoViewIfNeeded()
  assert.ok(await statuses.getByRole('listitem').last().isVisible(), 'Last chip remains reachable in the scrolling rail')
  await panel.screenshot({ path: join(tmpdir(), 'fpl-weekly-evidence-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await panel.scrollIntoViewIfNeeded()
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No mobile overflow')
  await page.screenshot({ path: join(tmpdir(), 'fpl-weekly-evidence-mobile.png') })
  await statuses.getByRole('listitem').last().scrollIntoViewIfNeeded()
  const lastChip = await statuses.getByRole('listitem').last().boundingBox()
  assert.ok(lastChip && lastChip.y < 844 && lastChip.y + lastChip.height > 0, 'All chips remain reachable on mobile')
  assert.deepEqual(errors, [], 'No browser errors')
  console.log('PASS: context-appropriate hold/transfer evidence, four-chip authority, mobile layout.')
  console.log('Screenshots:', join(tmpdir(), 'fpl-weekly-evidence-desktop.png'), join(tmpdir(), 'fpl-weekly-evidence-mobile.png'))
} finally {
  await browser.close()
}
