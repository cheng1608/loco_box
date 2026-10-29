import { expect, test, type Page } from '@playwright/test'

async function mockBackend(page: Page, state: { online: boolean; configOnline?: boolean; health?: unknown }) {
  await page.route('http://127.0.0.1:8790/api/**', async (route) => {
    if (!state.online) return route.abort('connectionrefused')
    const path = new URL(route.request().url()).pathname
    let body: unknown
    if (path === '/api/health') body = state.health ?? { service: 'loco_box', protocol: 1, ready: true }
    else if (path === '/api/status') body = { arduino_connected: false, port: null }
    else if (path === '/api/features') body = { features: [
      { id: 'box_monitor', name: '惊喜盒子', running: false },
      { id: 'throw', name: '丢球', running: false },
      { id: 'music', name: '自动演奏', running: false },
    ] }
    else if (path.endsWith('/config')) {
      if (state.configOnline === false) return route.abort('connectionrefused')
      body = { config: { delay: 2, threshold: 0.45, brightness: 200, trigger_delay: 5 } }
    }
    else if (path === '/api/music/state') body = { playlist: [], current: '', mode: 'single', running: false, paused: false }
    else if (path === '/api/music/scores') body = { scores: [] }
    else throw new Error(`Unexpected API request in startup test: ${path}`)
    return route.fulfill({ json: body, headers: { 'Access-Control-Allow-Origin': '*' } })
  })
  await page.routeWebSocket('ws://127.0.0.1:8790/ws**', () => {})
}

test('the feature panel recovers after the backend starts late without reloading', async ({ page }) => {
  const state = { online: false }
  await mockBackend(page, state)
  await page.goto('/')
  await expect(page.getByRole('status')).toContainText('正在连接本地服务')
  await expect(page.getByRole('button', { name: '连接 Arduino' })).toBeDisabled()

  state.online = true
  await expect(page.getByRole('heading', { name: '惊喜盒子' })).toBeVisible({ timeout: 10000 })
  await expect(page.getByRole('button', { name: '开始监控' })).toBeEnabled()
  await expect(page.getByRole('button', { name: '自动演奏', exact: true })).toBeVisible()
  await expect(page.getByRole('status')).toHaveCount(0)
})

test('a legacy backend cannot enable hardware actions and a compatible replacement recovers', async ({ page }) => {
  const state = { online: true, health: { status: 'ok' } as unknown }
  await mockBackend(page, state)
  const featureRequests: string[] = []
  page.on('request', (request) => {
    if (request.url().endsWith('/api/features')) featureRequests.push(request.url())
  })
  await page.goto('/')
  await expect(page.getByRole('status')).toContainText('本地服务启动失败')
  await page.getByText('查看连接详情', { exact: true }).click()
  await expect(page.getByText(/本地服务版本不兼容：8790/)).toBeVisible()
  await expect(page.getByRole('button', { name: '连接 Arduino' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '开始监控' })).toHaveCount(0)
  expect(featureRequests).toEqual([])

  state.health = { service: 'loco_box', protocol: 1, ready: true }
  await expect(page.getByRole('button', { name: '开始监控' })).toBeEnabled({ timeout: 10000 })
  await expect(page.getByRole('status')).toHaveCount(0)
})

test('backend interruption recovers and preserves unsaved form values', async ({ page }) => {
  const state = { online: true }
  await mockBackend(page, state)
  await page.goto('/')
  await expect(page.getByRole('button', { name: '开始监控' })).toBeEnabled()
  const delay = page.getByRole('spinbutton').first()
  await delay.fill('7')
  await delay.blur()

  state.online = false
  await expect(page.getByRole('status')).toContainText('本地服务连接中断', { timeout: 10000 })
  await expect(page.locator('.feature-content')).toHaveAttribute('inert', '')
  state.online = true
  await expect(page.getByRole('status')).toHaveCount(0, { timeout: 10000 })
  await expect(delay).toHaveValue('7')
  await expect(page.locator('.feature-content')).not.toHaveAttribute('inert', '')
})

test('configuration failures retry before enabling hardware actions', async ({ page }) => {
  const state = { online: true, configOnline: false }
  await mockBackend(page, state)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '惊喜盒子' })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始监控' })).toBeDisabled()
  await expect(page.getByText(/配置加载失败，正在重试/)).toBeVisible()
  state.configOnline = true
  await expect(page.getByRole('button', { name: '开始监控' })).toBeEnabled({ timeout: 10000 })
  await expect(page.getByRole('spinbutton').first()).toHaveValue('2')
})

test('panels share one websocket and folding preview unsubscribes from frames', async ({ page }) => {
  await mockBackend(page, { online: true })
  const sockets: string[] = []
  // Observe constructor calls, including sockets intercepted by routeWebSocket.
  await page.exposeFunction('recordSocket', (url: string) => sockets.push(url))
  await page.addInitScript(() => {
    const OriginalWebSocket = window.WebSocket
    window.WebSocket = class extends OriginalWebSocket {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols)
        ;(window as any).recordSocket(String(url))
      }
    }
  })
  await page.goto('/')
  await expect(page.getByRole('button', { name: '开始监控' })).toBeEnabled()
  expect(sockets).toEqual(['ws://127.0.0.1:8790/ws?preview=1'])
  await page.getByRole('button', { name: '丢球', exact: true }).click()
  await expect(page.getByRole('heading', { name: '丢球', exact: true })).toBeVisible()
  expect(sockets).toHaveLength(1)
  await page.getByTitle('折叠到右侧').click()
  await expect.poll(() => sockets.at(-1)).toBe('ws://127.0.0.1:8790/ws')
  await page.getByTitle('展开预览').click()
  await expect.poll(() => sockets.at(-1)).toBe('ws://127.0.0.1:8790/ws?preview=1')
})

test('an overlay mounts directly without fetching the main window panels', async ({ page }) => {
  await mockBackend(page, { online: true })
  const requests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/')) requests.push(request.url())
  })
  await page.addInitScript(() => {
    ;(window as any).isTauri = true
    ;(window as any).__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: 'box_overlay' }, currentWebview: { label: 'box_overlay' } },
      invoke: async () => null,
    }
  })
  await page.goto('/')
  await expect(page.locator('.box')).toBeVisible()
  await expect(page.locator('.sidebar')).toHaveCount(0)
  expect(requests).toEqual([])
})
