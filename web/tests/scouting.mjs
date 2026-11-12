// Uses real saved data, then intercepts ALL API calls; no account/optimiser writes.
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const origin = process.env.FPLAGENT_TEST_ORIGIN ?? 'http://127.0.0.1:5173'
const workspace = await (await fetch(`${origin}/api/v1/workspace`)).json()
const board = await (await fetch(`${origin}/api/v1/scouting`)).json()
assert.equal(board.status, 'ready')
const cache = join(homedir(), '.cache', 'ms-playwright')
const executablePath = readdirSync(cache).filter(n => /^chromium-\d+$/.test(n)).sort().reverse()
  .map(n => join(cache, n, 'chrome-linux64', 'chrome')).find(existsSync)
const browser = await chromium.launch({ executablePath, headless: true })
const page = await browser.newPage({ viewport: { width: 1512, height: 1080 } })
const errors = []
page.on('pageerror', e => errors.push(e.message))
let failRefresh = false
await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname
  let body = {}
  if (path === '/api/v1/workspace') body = workspace
  else if (path.startsWith('/api/v1/scouting')) {
    if (path.endsWith('/refresh') && failRefresh) return route.fulfill({ status: 503, json: {} })
    body = board
  } else if (path === '/api/v1/integrations/fpl') body = { status: 'disconnected' }
  else if (path === '/api/v1/workspace/refresh') body = { schema_version: 'workspace-refresh-v1', status: 'idle', mode: 'weekly', published: false, reused: false, completed_stages: [] }
  else if (path === '/api/v1/workspace/refresh/schedule') body = { schema_version: 'deadline-refresh-schedule-v1', status: 'covered', event: 8, cadence_label: 'QA only' }
  await route.fulfill({ json: body })
})
try {
  await page.goto(origin)
  await page.getByRole('button', { name: 'Player scouting', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Compare the evidence.' })
  await dialog.locator('.scout-player').first().waitFor()
  assert.equal(await dialog.locator('.scout-player').count(), 2)
  const search = dialog.getByPlaceholder('Player or club')
  const first = board.players.find(p => p.name === 'B.Fernandes')
  const second = board.players.find(p => p.name === 'Semenyo')
  await search.fill(first.name)
  await dialog.getByRole('button', { name: `Compare ${first.name} on left`, exact: true }).click()
  await search.fill(second.name)
  await dialog.getByRole('button', { name: `Compare ${second.name} on right`, exact: true }).click()
  assert.equal(await dialog.locator('.scout-player').first().getByRole('heading', { level: 3 }).textContent(), first.name)
  assert.equal(await dialog.locator('.scout-player').last().getByRole('heading', { level: 3 }).textContent(), second.name)
  assert.ok(await dialog.getByText(/Out of date: refresh decisions/).count() > 0)
  assert.equal(await dialog.getByText('What the average can hide', { exact: true }).count(), 2)
  await search.fill('NoSuchPlayerTest')
  await dialog.getByText(/No players match/).waitFor()
  assert.equal(await dialog.locator('.scout-player').count(), 2)
  await search.fill('')
  await dialog.getByLabel('Order shortlist by').selectOption('defcon')
  assert.ok(await dialog.locator('.scout-shortlist').getByText(/DEFCON/).count() > 0)
  await dialog.getByLabel('Order shortlist by').selectOption('xgi')
  failRefresh = true
  await dialog.getByRole('button', { name: 'Update scouting', exact: true }).click()
  await dialog.getByRole('alert').waitFor()
  assert.equal(await dialog.locator('.scout-player').count(), 2)
  failRefresh = false
  await dialog.getByRole('button', { name: 'Update scouting', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.scout-dialog [role=alert]'))
  mkdirSync('../data/web/qa', { recursive: true })
  await dialog.screenshot({ path: '../data/web/qa/scouting-desktop.png' })
  await dialog.locator('.scout-comparison').scrollIntoViewIfNeeded()
  await dialog.screenshot({ path: '../data/web/qa/scouting-comparison.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  await dialog.evaluate(el => el.scrollTop = 0)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
  await dialog.screenshot({ path: '../data/web/qa/scouting-mobile.png' })
  await dialog.locator('.scout-player').first().scrollIntoViewIfNeeded()
  await dialog.screenshot({ path: '../data/web/qa/scouting-mobile-comparison.png' })
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual(errors, [])
  console.log('Scouting QA passed: real data, A/B selection, search, stale labels, distributions, failure retention, desktop/mobile and Escape.')
} finally { await browser.close() }
