import { expect, test, type Page, type WebSocketRoute } from '@playwright/test'
import type { PetDetails, PetViewerState } from '../src/api/client'

const firstPet: PetDetails = {
  id: '18446744073709551614', name: '喵喵', nature: '固执', nature_id: 2,
  nature_hint: '物攻↑ 魔攻↓', nature_tip: '原始性格：固执（编号：2）\n战斗属性修正：生命↑ 速度↓；对应属性组合：踏实',
  nature_modified: true, nature_effective: '踏实', bloodline_label: '异色·奇异', shiny: true,
  shiny_hint: '异色', voice: 99, voice_hint: '婉转声', height: 100, height_hint: '',
  weight: 99.5, weight_hint: '大块头',
}
const secondPet: PetDetails = {
  ...firstPet, id: '18446744073709551615', name: '火花', nature: '大胆', nature_id: 1,
  nature_hint: '物攻↑ 物防↓', nature_tip: '原始性格：大胆（编号：1）', shiny: false,
  bloodline_label: '普通', voice: null, height: null, weight: null, voice_hint: '', weight_hint: '',
}

async function setupPetViewer(page: Page, options: { driver?: boolean; resources?: boolean; overlay?: boolean; active?: boolean } = {}) {
  const state: PetViewerState = {
    session_id: 'service-one', running: !!options.active, phase: options.active ? 'active' : 'stopped',
    status: options.active ? '已读取' : '已停止', message: '', source: '实时', revision: 1,
    resources: { ready: options.resources !== false, message: options.resources === false ? '缺少协议资源 all.pb' : '资源已就绪' },
    npcap_available: options.driver !== false, packet_count: 0, decoded_count: 0,
    pets: options.active ? [firstPet, secondPet] : [], selected: options.active ? firstPet : null,
  }
  const commands: { path: string; data: Record<string, unknown> }[] = []
  const requests: string[] = []
  let adapter = ''
  let socket: WebSocketRoute | null = null
  let heldState: { started: boolean; wait: Promise<void> } | null = null
  let heldConfig: { started: boolean; wait: Promise<void> } | null = null
  await page.routeWebSocket('ws://127.0.0.1:8790/ws**', ws => { socket = ws })
  await page.route('http://127.0.0.1:8790/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    requests.push(path)
    const data = request.method() === 'GET' ? {} : request.postDataJSON() ?? {}
    if (request.method() !== 'GET') commands.push({ path, data })
    let body: unknown
    if (path === '/api/health') body = { service: 'loco_box', protocol: 1, ready: true }
    else if (path === '/api/status') body = { arduino_connected: false, port: null }
    else if (path === '/api/features') body = { features: [{ id: 'pet_viewer', name: '精灵查看', running: state.running }] }
    else if (path === '/api/features/pet_viewer/config') {
      if (request.method() === 'PUT') {
        if (heldConfig) {
          const hold = heldConfig
          heldConfig = null
          hold.started = true
          await hold.wait
        }
        adapter = data.config.adapter
      }
      body = { config: { adapter }, ok: true }
    } else if (path === '/api/features/pet_viewer/start') {
      Object.assign(state, { running: true, phase: 'waiting', status: '等待连接', message: '请进入游戏世界', revision: state.revision + 1, source: '实时', pets: [], selected: null })
      body = { ok: true, running: true }
    } else if (path === '/api/features/pet_viewer/stop') {
      Object.assign(state, { running: false, phase: 'stopped', status: '已停止', revision: state.revision + 1, pets: [], selected: null })
      body = { ok: true }
    } else if (path === '/api/pet-viewer/state') {
      body = structuredClone(state)
      if (heldState) {
        const hold = heldState
        heldState = null
        hold.started = true
        await hold.wait
      }
    } else if (path === '/api/pet-viewer/adapters') body = {
      available: options.driver !== false,
      adapters: options.driver === false ? [] : [{ name: 'wifi-adapter', description: 'Wi-Fi 无线网络' }],
      message: options.driver === false ? '未安装 Npcap，请安装官方驱动' : '',
    }
    else if (path === '/api/pet-viewer/demo') {
      Object.assign(state, { running: false, phase: 'ended', status: '回放完成', source: '示例回放', revision: state.revision + 1, pets: [firstPet], selected: firstPet })
      body = state
    } else if (path === '/api/pet-viewer/select') {
      state.selected = state.pets.find(pet => pet.id === data.pet_id) ?? null
      state.revision++
      body = state
    } else if (path === '/api/pet-viewer/history') body = { items: [], total: 0 }
    else throw new Error(`Unhandled pet-viewer endpoint ${path}`)
    await route.fulfill({ json: body, headers: { 'Access-Control-Allow-Origin': '*' } })
  })
  if (options.overlay) await page.addInitScript(() => {
    const calls: string[] = []
    ;(window as any).tauriCalls = calls
    ;(window as any).isTauri = true
    ;(window as any).__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: 'pet_overlay' }, currentWebview: { label: 'pet_overlay' } },
      invoke: async (command: string) => { calls.push(command); return null },
    }
  })
  await page.goto('/')
  if (options.overlay) await expect(page.locator('.pet-overlay')).toBeVisible()
  else await expect(page.getByRole('heading', { name: '精灵查看', exact: true })).toBeVisible()
  await expect.poll(() => requests.includes('/api/pet-viewer/state')).toBe(true)
  return {
    state, commands, requests,
    update(patch: Partial<PetViewerState>) {
      Object.assign(state, patch, { revision: state.revision + 1 })
      socket?.send(JSON.stringify({ type: 'event', name: 'pet_viewer.state', data: state }))
    },
    holdNextState() {
      let release: () => void = () => {}
      const hold = { started: false, wait: new Promise<void>(resolve => { release = resolve }) }
      heldState = hold
      return { get started() { return hold.started }, release }
    },
    holdNextConfig() {
      let release: () => void = () => {}
      const hold = { started: false, wait: new Promise<void>(resolve => { release = resolve }) }
      heldConfig = hold
      return { get started() { return hold.started }, release }
    },
  }
}

test('missing capture driver still permits an explicitly labelled demo without Arduino', async ({ page }) => {
  const fixture = await setupPetViewer(page, { driver: false })
  await expect(page.getByRole('button', { name: '开始监听', exact: true })).toBeDisabled()
  await expect(page.getByText('未安装 Npcap，请安装官方驱动')).toBeVisible()
  await expect(page.getByRole('link', { name: '打开 Npcap 官方下载页 ↗' })).toHaveAttribute('href', 'https://npcap.com/#download')
  await page.getByRole('button', { name: '示例回放', exact: true }).click()
  await expect(page.getByTestId('pet-nature')).toHaveText('固执')
  await expect(page.getByText('当前显示合成示例数据，不代表真实遭遇，也不会写入历史记录。')).toBeVisible()
  await page.getByText('查看属性详情').click()
  await expect(page.locator('.pet-evidence')).toContainText('战斗属性修正：生命↑ 速度↓')
  await page.getByText('本机遭遇记录', { exact: false }).click()
  await expect(page.getByText('暂无记录，真实遭遇会自动保存在本机。')).toBeVisible()
  expect(fixture.commands.map(item => item.path)).toEqual(['/api/pet-viewer/demo'])
})

test('starts the chosen adapter and clears stale attributes when PVP is blocked', async ({ page }) => {
  const fixture = await setupPetViewer(page)
  await page.getByLabel('监听网卡').selectOption('wifi-adapter')
  await page.getByRole('button', { name: '开始监听', exact: true }).click()
  await expect(page.getByRole('button', { name: '停止监听' })).toBeVisible()
  expect(fixture.commands[0]).toEqual({ path: '/api/features/pet_viewer/config', data: { config: { adapter: 'wifi-adapter' } } })
  fixture.update({ phase: 'active', status: '已读取', message: '', pets: [firstPet], selected: firstPet })
  await expect(page.getByTestId('pet-nature')).toHaveText('固执')
  fixture.update({ phase: 'blocked', status: '玩家 PVP 已阻断', message: '玩家目标不读取或保存属性', pets: [], selected: null })
  await expect(page.getByTestId('pet-nature')).toHaveCount(0)
  await expect(page.getByText('玩家目标不读取或保存属性')).toBeVisible()
  expect(fixture.commands.some(item => item.path.includes('/arduino/'))).toBe(false)
})

test('preserves uint64 pet IDs and represents absent attributes as unknown', async ({ page }) => {
  const fixture = await setupPetViewer(page, { active: true })
  await page.getByRole('button', { name: '火花', exact: true }).click()
  await expect(page.getByTestId('pet-nature')).toHaveText('大胆')
  expect(fixture.commands.at(-1)).toEqual({ path: '/api/pet-viewer/select', data: { pet_id: '18446744073709551615' } })
  await expect(page.locator('.pet-metrics strong')).toHaveText(['—', '—', '—'])
  await expect(page.locator('.pet-metrics small')).toHaveText(['未下发', '未下发', '未下发'])
})

test('an older HTTP snapshot cannot overwrite a newer websocket encounter', async ({ page }) => {
  const fixture = await setupPetViewer(page, { active: true })
  await expect(page.getByTestId('pet-nature')).toHaveText('固执')
  const hold = fixture.holdNextState()
  await expect.poll(() => hold.started).toBe(true)
  fixture.update({ pets: [secondPet], selected: secondPet })
  await expect(page.getByTestId('pet-nature')).toHaveText('大胆')
  hold.release()
  await expect(page.getByTestId('pet-nature')).toHaveText('大胆')
})

test('resource errors disable capture and demo while the rest of the panel remains available', async ({ page }) => {
  await setupPetViewer(page, { resources: false })
  await expect(page.getByRole('alert')).toContainText('缺少协议资源 all.pb')
  await expect(page.getByRole('button', { name: '开始监听', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '示例回放', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '刷新网卡' })).toBeEnabled()
})

test('stopping while configuration saves cancels the pending start', async ({ page }) => {
  const fixture = await setupPetViewer(page)
  const hold = fixture.holdNextConfig()
  await page.getByRole('button', { name: '开始监听', exact: true }).click()
  await expect.poll(() => hold.started).toBe(true)
  await page.getByRole('button', { name: '停止监听', exact: true }).click()
  hold.release()
  await expect(page.getByRole('button', { name: '开始监听', exact: true })).toBeEnabled()
  expect(fixture.commands.map(item => item.path)).toEqual(['/api/features/pet_viewer/config', '/api/features/pet_viewer/stop'])
  expect(fixture.state.running).toBe(false)
})

test('overlay mounts directly and can close while leaving capture running', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 360 })
  const fixture = await setupPetViewer(page, { active: true, overlay: true })
  await expect(page.locator('.sidebar')).toHaveCount(0)
  await expect(page.getByTestId('pet-nature')).toHaveText('固执')
  await expect(page.getByRole('button', { name: '停止监听' })).toBeInViewport()
  await page.getByRole('button', { name: '关闭悬浮窗，继续监听' }).click()
  expect(await page.evaluate(() => (window as any).tauriCalls)).toContain('hide_pet_overlay')
  expect(fixture.commands).toEqual([])
  expect(fixture.requests).not.toContain('/api/features')
})
