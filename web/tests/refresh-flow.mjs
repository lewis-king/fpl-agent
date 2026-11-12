// Browser regression with isolated API mocks. No credentials, real syncs or refresh writes.
// Start the local API and Vite first; pass CHROMIUM_EXECUTABLE_PATH if needed.
import assert from 'node:assert/strict'
import { existsSync, readdirSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const origin = process.env.FPLAGENT_TEST_ORIGIN ?? 'http://127.0.0.1:5173'
const workspace = await (await fetch(`${origin}/api/v1/workspace`)).json()
const event = workspace.phase.decision_event
const cache = join(homedir(), '.cache', 'ms-playwright')
const executablePath = process.env.CHROMIUM_EXECUTABLE_PATH ?? readdirSync(cache)
  .filter(name => /^chromium-\d+$/.test(name)).sort().reverse()
  .map(name => join(cache, name, 'chrome-linux64', 'chrome')).find(existsSync)
assert.ok(executablePath, 'Install a Playwright Chromium or set CHROMIUM_EXECUTABLE_PATH')
const browser = await chromium.launch({ executablePath, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
let authenticated = false
let synced = 0
let loginAllowed = false
const starts = []
let run = {
  schema_version: 'workspace-refresh-v1', run_id: 'previous-run', status: 'not_ready',
  event, mode: 'weekly', completed_stage_count: 0, completed_stages: [], total_stages: null,
  started_at: '2026-09-09T07:04:19Z', completed_at: '2026-09-09T07:04:32Z',
  message: 'Reconnect FPL: the private squad snapshot predates the previous deadline.',
}
const schedule = () => ({
  schema_version: 'deadline-refresh-schedule-v1', event, cadence_label: '6-hour cadence',
  status: run.status === 'running' ? 'running' : run.status === 'published' ? 'covered' : 'waiting',
  last_attempt_at: run.started_at,
  last_validated_at: run.status === 'published' ? run.completed_at : null,
  next_window_at: run.status === 'published' ? '2026-09-09T13:13:32Z' : null,
  message: 'Waiting for new manager evidence.',
})
await page.route('**/mock-login*', route => route.fulfill({ contentType: 'text/html', body: '<p>Test login — no credentials needed.</p>' }))
await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname
  let body
  if (path === '/api/v1/workspace') body = { ...workspace, user: { ...workspace.user, sync_state: authenticated ? 'mcp_connected' : 'unconnected' } }
  else if (path === '/api/v1/integrations/fpl') body = { status: authenticated ? 'connected' : 'not_authenticated' }
  else if (path === '/api/v1/integrations/fpl/login') body = { request_id: 'mock', login_url: `${origin}/mock-login` }
  else if (path === '/api/v1/integrations/fpl/login/mock') {
    authenticated = loginAllowed
    body = { status: loginAllowed ? 'authenticated' : 'pending' }
  } else if (path === '/api/v1/integrations/fpl/sync') {
    synced++
    body = { entry_id: workspace.user.fpl_entry_id, status: 'synced', manager_state_status: 'ready' }
  } else if (path === '/api/v1/workspace/refresh/schedule') body = schedule()
  else if (path === '/api/v1/workspace/refresh') {
    if (route.request().method() === 'POST') {
      starts.push(route.request().postDataJSON().reason)
      if (authenticated) run = { ...run, run_id: 'after-login', status: 'running', started_at: '2026-09-09T07:11:50Z', completed_at: null,
        current_stage: 'weekly_optimisation', total_stages: 5, completed_stage_count: 2, progress_percent: 40,
        message: 'Comparing transfers, all 15 players, captaincy and chips.' }
    }
    body = run
  } else body = {}
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
})

try {
  await page.goto(origin)
  await page.getByText(`GW${event} refresh needs input — not running`, { exact: true }).waitFor()
  await page.getByText(run.message, { exact: true }).waitFor({ state: 'visible' })
  assert.equal(await page.getByText('The previous validated workspace remains active while uncertain player roles are checked.').count(), 0)
  loginAllowed = true
  await page.getByText(`GW${event} decision refresh running`, { exact: true }).waitFor()
  assert.equal(synced, 1)
  assert.deepEqual(starts, ['app_open', 'manual'])
  assert.equal(await page.getByRole('dialog').count(), 0, 'Successful connection returns to the workspace')
  assert.ok(await page.getByText('2/5 stages').isVisible())

  run = { ...run, status: 'published', completed_at: '2026-09-09T07:13:32Z', message: 'The weekly decision passed every evidence gate and is now active.' }
  await page.getByText(`GW${event} decision validated`, { exact: true }).waitFor()
  await page.getByText(`GW${event} last validated`, { exact: true }).waitFor()
  const timeline = page.getByRole('definition').filter({ hasText: /Sept/ })
  assert.ok(await timeline.count() >= 2)
  await page.screenshot({ path: join(tmpdir(), 'fpl-refresh-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: join(tmpdir(), 'fpl-refresh-mobile.png') })
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No mobile horizontal overflow')

  // A scheduler or second tab starts another worker: this page must follow it.
  run = { ...run, run_id: 'external-worker', status: 'running', completed_at: null, message: 'External worker testing transfers.' }
  await page.getByText(`GW${event} decision refresh running`, { exact: true }).waitFor()
  run = { ...run, status: 'blocked', completed_at: '2026-09-09T07:20:00Z', message: 'Forecast generation changed during validation.' }
  await page.getByText(run.message, { exact: true }).waitFor()
  assert.ok(await page.getByText(`GW${event} refresh needs input — not running`, { exact: true }).isVisible())
  assert.deepEqual(starts, ['app_open', 'manual'], 'Status polling must never launch extra work')
  assert.deepEqual(errors, [], 'No browser runtime errors')
  console.log('PASS: login → sync → refresh → publication; external workers; exact blockers; timestamps; mobile layout.')
  console.log('Screenshots:', join(tmpdir(), 'fpl-refresh-desktop.png'), join(tmpdir(), 'fpl-refresh-mobile.png'))
} catch (error) {
  console.error('Visible notices:', await page.locator('.run-notice').innerText().catch(() => 'no notice'))
  console.error('Browser errors:', errors)
  await page.screenshot({ path: join(tmpdir(), 'fpl-refresh-failure.png') })
  throw error
} finally {
  await browser.close()
}
