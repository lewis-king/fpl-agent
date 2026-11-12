// Presentation-only QA: every browser API call is mocked, including refreshes.
import assert from 'node:assert/strict'
import { existsSync, readdirSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const origin = process.env.FPLAGENT_TEST_ORIGIN ?? 'http://127.0.0.1:5173'
const workspace = await (await fetch(`${origin}/api/v1/workspace`)).json()
const advice = workspace.decision.weekly.chip_advice
delete advice.needs_review // Exercise compatibility with an already running older API.
advice.recommendation = 'no_chip'
advice.candidate_statuses = [{ chip: 'wildcard', status: 'research_only', joint_net_value: 7.2, blockers: ['historical outcome authority'] }]
workspace.decision.weekly.status = 'ready'
workspace.user.sync_state = 'mcp_connected'
const cache = join(homedir(), '.cache', 'ms-playwright')
const executablePath = process.env.CHROMIUM_EXECUTABLE_PATH ?? readdirSync(cache)
  .filter(name => /^chromium-\d+$/.test(name)).sort().reverse()
  .map(name => join(cache, name, 'chrome-linux64', 'chrome')).find(existsSync)
assert.ok(executablePath)
const browser = await chromium.launch({ executablePath, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname
  let body = {}
  if (path === '/api/v1/workspace') body = workspace
  else if (path === '/api/v1/integrations/fpl') body = { status: 'connected' }
  else if (path.endsWith('/refresh/schedule')) body = { status: 'covered', event: 8, cadence_label: '2-hour cadence' }
  else if (path.endsWith('/refresh')) body = { status: 'published', event: 8, published: true, run_id: 'mock', message: 'Frozen test data' }
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
})
try {
  await page.goto(origin)
  await page.getByText('Chip decision unresolved', { exact: true }).waitFor()
  assert.ok(await page.getByRole('heading', { name: 'Review chips before making transfers' }).isVisible())
  assert.ok(await page.getByText('Review before taking a hit', { exact: false }).isVisible())
  assert.ok(await page.locator('details[open]').filter({ hasText: 'Chip decision unresolved' }).count())
  await page.getByText('Chip decision unresolved', { exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: join(tmpdir(), 'fpl-chip-review-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByText('Chip decision unresolved', { exact: true }).scrollIntoViewIfNeeded()
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
  await page.screenshot({ path: join(tmpdir(), 'fpl-chip-review-mobile.png') })
  assert.deepEqual(errors, [])
  console.log('PASS: unresolved chip warning visible/expanded; old API compatible; no mobile overflow or browser errors. No live writes.')
} finally {
  await browser.close()
}
