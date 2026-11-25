import { expect, test, type Page } from '@playwright/test'

async function mockDesktop(page: Page, label: string) {
  await page.addInitScript(label => {
    const calls: { command: string; args: unknown }[] = []
    ;(window as any).tauriCalls = calls
    ;(window as any).isTauri = true
    ;(window as any).__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label }, currentWebview: { label } },
      invoke: async (command: string, args: unknown) => { calls.push({ command, args }); return null },
    }
  }, label)
  await page.routeWebSocket('ws://127.0.0.1:8790/ws**', () => {})
}

test('box overlay keeps the stop control visible and reports failures before retrying', async ({ page }) => {
  await mockDesktop(page, 'box_overlay')
  let fails = true
  await page.route('http://127.0.0.1:8790/api/features/box_monitor/stop', route => route.fulfill({
    status: fails ? 503 : 200,
    json: fails ? { detail: '停止监控失败，请重试' } : { ok: true },
    headers: { 'Access-Control-Allow-Origin': '*' },
  }))
  await page.goto('/')
  await page.getByRole('button', { name: '停止并关闭' }).click()
  await expect(page.getByRole('alert')).toHaveText('停止监控失败，请重试')
  expect(await page.evaluate(() => (window as any).tauriCalls)).toEqual([])
  fails = false
  await page.getByRole('button', { name: '停止并关闭' }).click()
  await expect.poll(() => page.evaluate(() => (window as any).tauriCalls.map((call: any) => call.command))).toContain('hide_box_overlay')
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('throw overlay prevents duplicate commands and lets failed starts retry immediately', async ({ page }) => {
  await mockDesktop(page, 'overlay')
  let starts = 0
  let release: () => void = () => {}
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('http://127.0.0.1:8790/api/features', route => route.fulfill({
    json: { features: [{ id: 'throw', name: '丢球', running: false }] },
    headers: { 'Access-Control-Allow-Origin': '*' },
  }))
  await page.route('http://127.0.0.1:8790/api/features/throw/start', async route => {
    starts++
    if (starts === 1) await gate
    return route.fulfill({
      status: starts === 1 ? 503 : 200,
      json: starts === 1 ? { detail: '设备连接失败' } : { ok: true, running: true },
      headers: { 'Access-Control-Allow-Origin': '*' },
    })
  })
  await page.goto('/')
  const button = page.getByRole('button', { name: '丢球', exact: true })
  await button.click()
  await expect(button).toBeDisabled()
  await button.dispatchEvent('click')
  expect(starts).toBe(1)
  release()
  await expect(page.getByRole('alert')).toHaveText('设备连接失败')
  await expect(button).toBeEnabled()
  await button.click()
  await expect(page.getByRole('button', { name: /冷却中/ })).toBeDisabled()
  expect(starts).toBe(2)
  await expect(page.getByRole('alert')).toHaveCount(0)
})
