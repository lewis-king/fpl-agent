// Browser QA with real saved read models, then isolated API routes. No FPL writes,
// authentication or decision refreshes are allowed from this test browser.
import assert from 'node:assert/strict'
import { existsSync, mkdirSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const origin = process.env.FPLAGENT_TEST_ORIGIN ?? 'http://127.0.0.1:5173'
const workspace = await (await fetch(`${origin}/api/v1/workspace`)).json()
const review = await (await fetch(`${origin}/api/v1/review`)).json()
assert.equal(review.status, 'ready')
const cache = join(homedir(), '.cache', 'ms-playwright')
const executablePath = readdirSync(cache).filter(name => /^chromium-\d+$/.test(name)).sort().reverse()
  .map(name => join(cache, name, 'chrome-linux64', 'chrome')).find(existsSync)
const browser = await chromium.launch({ executablePath, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
let failRefresh = false
await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname
  let body = {}
  if (path === '/api/v1/workspace') body = workspace
  else if (path === '/api/v1/review' || path === '/api/v1/review/refresh') {
    if (path.endsWith('/refresh') && failRefresh) return route.fulfill({ status: 503, json: { detail: 'Test failure' } })
    body = review
  } else if (path === '/api/v1/integrations/fpl') body = { status: 'disconnected' }
  else if (path === '/api/v1/workspace/refresh') body = {
    schema_version: 'workspace-refresh-v1', status: 'idle', mode: 'weekly', published: false,
    reused: false, completed_stages: [], message: 'Isolated review test; no refresh running.',
  }
  else if (path === '/api/v1/workspace/refresh/schedule') body = {
    schema_version: 'deadline-refresh-schedule-v1', status: 'covered', event: 8,
    cadence_label: 'Test', message: 'Read-only browser test.',
  }
  await route.fulfill({ json: body })
})
try {
  await page.goto(origin)
  await page.getByRole('button', { name: 'Season review', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'What actually happened.' })
  await dialog.getByText(`${review.total_points} points`, { exact: true }).waitFor()
  assert.equal(await dialog.evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(246, 247, 241)', 'Review requires an opaque readable surface')
  assert.equal(await dialog.locator('tbody tr').count(), 15)
  await dialog.getByText('Forecast reliability · all reviewed weeks', { exact: true }).waitFor()
  assert.ok(await dialog.getByText('Semenyo', { exact: false }).count())
  const select = dialog.getByLabel('Review gameweek')
  await select.selectOption(String(review.events[0].event))
  await dialog.getByText(`Your GW${review.events[0].event}`, { exact: true }).waitFor()
  await select.selectOption(String(review.events.at(-1).event))
  await dialog.getByText('What this review can—and cannot—tell us').click()
  await dialog.getByText(/Those figures overlap/).waitFor()
  failRefresh = true
  await dialog.getByRole('button', { name: 'Refresh results' }).click()
  await dialog.getByRole('alert').waitFor()
  assert.equal(await dialog.locator('tbody tr').count(), 15, 'Failed refresh retains the saved review')
  failRefresh = false
  await dialog.getByRole('button', { name: 'Refresh results' }).click()
  await page.waitForFunction(() => !document.querySelector('.season-review [role=alert]'))
  mkdirSync('../data/web/qa', { recursive: true })
  await dialog.screenshot({ path: '../data/web/qa/season-review-desktop.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  const width = await dialog.evaluate(el => el.getBoundingClientRect().width)
  assert.ok(width <= 390, 'Dialog must fit the mobile viewport')
  await dialog.screenshot({ path: '../data/web/qa/season-review-mobile.png' })
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual(errors, [])
  console.log('Season review: real data, event switching, failure retention, retry, desktop/mobile and Escape passed.')
} finally {
  await browser.close()
}
