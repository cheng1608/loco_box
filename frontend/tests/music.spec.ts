import { expect, test, type Page, type WebSocketRoute } from '@playwright/test'

const midi = { id: 'midi-one', name: '练习和弦', filename: '练习和弦.mid', format: 'midi', duration_ms: 60000, note_count: 12, track_count: 3 }
const second = { id: 'midi-two', name: '另一首', filename: '另一首.mid', format: 'midi', duration_ms: 30000, note_count: 8, track_count: 2 }
const legacy = { id: 'txt-one', name: '旧谱', filename: '旧谱.txt', format: 'txt', duration_ms: 5000, note_count: 10, track_count: 1 }
const initialSettings = { selected_tracks: null as number[] | null, transpose: 0, range_policy: 'degree', root: null as number | null, conflict_policy: 'adapt', mapping_version: 2, speed: 1, skip_leading_silence: true }

async function setupMusic(page: Page, options: { legacyFirmware?: boolean; playing?: boolean; overlay?: boolean; selectedId?: string; stateDelay?: number; unmappedNotes?: number } = {}) {
  let online = true
  let stopFails = false
  let deleteFails = false
  let stateRequests = 0
  const songs = [{ ...midi }, { ...second }, { ...legacy }]
  const state = {
    playlist: songs.map(song => song.filename), current: midi.filename, mode: 'sequential',
    running: !!options.playing, paused: false, phase: options.playing ? 'playing' : 'stopped',
    selected_song_id: options.selectedId ?? midi.id, playing_song_id: options.playing ? midi.id : null as string | null,
    playing_name: options.playing ? midi.name : '', position_ms: options.playing ? 12500 : 0,
    duration_ms: options.playing ? 60000 : 0, speed: 1, countdown_remaining: 0, revision: 1,
    error: null as { code: string; message: string } | null,
    device: options.legacyFirmware ? { connected: true, protocol: 1, max_keys: 1, midi_supported: false } : { connected: false, protocol: 0, max_keys: 0, midi_supported: false },
  }
  const settings = new Map(songs.map(song => [song.id, { ...initialSettings }]))
  const uploads: { filename: string; bytes: number; contentType: string }[] = []
  const commands: string[] = []
  let socket: WebSocketRoute | null = null
  await page.routeWebSocket('ws://127.0.0.1:8790/ws**', ws => { socket = ws })
  await page.route('http://127.0.0.1:8790/api/**', async route => {
    if (!online) return route.abort('connectionrefused')
    const request = route.request()
    const url = new URL(request.url())
    const endpoint = url.pathname
    const data = request.method() === 'GET' || endpoint.endsWith('/import') ? {} : request.postDataJSON() ?? {}
    let body: unknown
    if (endpoint === '/api/health') body = { service: 'loco_box', protocol: 1, ready: true }
    else if (endpoint === '/api/status') body = { arduino_connected: state.device.connected, port: null }
    else if (endpoint === '/api/features') body = { features: [{ id: 'music', name: '自动演奏', running: state.running }] }
    else if (endpoint === '/api/music/library') body = { songs }
    else if (endpoint === '/api/music/state') {
      if (stateRequests++ === 0 && options.stateDelay) await new Promise(resolve => setTimeout(resolve, options.stateDelay))
      body = state
    }
    else if (endpoint === '/api/music/import') {
      const filename = url.searchParams.get('filename')!
      uploads.push({ filename, bytes: request.postDataBuffer()?.length ?? 0, contentType: request.headers()['content-type'] })
      if (filename === '损坏.mid') return route.fulfill({ status: 400, json: { detail: { code: 'invalid_midi', message: '文件不是有效的 MIDI' } } })
      let song = songs.find(song => song.filename === filename)
      const duplicate = !!song
      if (!song) { song = { ...midi, id: `import-${songs.length}`, name: filename.replace(/\.[^.]+$/, ''), filename }; songs.push(song); settings.set(song.id, { ...initialSettings }) }
      body = { song, duplicate }
    } else if (endpoint.startsWith('/api/music/songs/') && request.method() === 'DELETE') {
      const id = decodeURIComponent(endpoint.split('/')[4])
      if (deleteFails) return route.fulfill({ status: 500, json: { detail: '曲目删除失败，请重试' } })
      if (state.running && state.playing_song_id === id) return route.fulfill({ status: 409, json: { detail: '请先停止这首曲目的演奏' } })
      const index = songs.findIndex(song => song.id === id)
      songs.splice(index, 1)
      settings.delete(id)
      state.playlist = songs.map(song => song.filename)
      if (state.selected_song_id === id) {
        const selected = songs[Math.min(index, songs.length - 1)]
        state.selected_song_id = selected?.id ?? ''
        state.current = selected?.filename ?? ''
      }
      if (state.playing_song_id === id) {
        Object.assign(state, { playing_song_id: '', playing_name: '', position_ms: 0, duration_ms: 0, phase: 'stopped' })
      }
      state.revision++
      commands.push('delete:' + id)
      body = { ok: true, song_id: id, songs, state }
    } else if (endpoint.startsWith('/api/music/songs/')) {
      const id = decodeURIComponent(endpoint.split('/')[4])
      const song = songs.find(song => song.id === id)!
      if (request.method() === 'PUT') settings.set(id, data)
      const unmapped = song.format === 'midi' ? options.unmappedNotes ?? 0 : 0
      const capacityConflict = state.device.midi_supported && state.device.max_keys < 3
      body = {
        song, settings: settings.get(id),
        tracks: song.format === 'txt' ? [] : [
          { id: 0, name: '旋律', channels: [0], note_count: 8, pitch_min: 64, pitch_max: 76, percussion: false },
          { id: 1, name: '伴奏', channels: [1], note_count: 4, pitch_min: 57, pitch_max: 72, percussion: false },
          { id: 2, name: '鼓', channels: [9], note_count: 4, pitch_min: 36, pitch_max: 42, percussion: true },
        ],
        analysis: { source_notes: 12, playable_notes: 12, chord_count: 3, max_keys: capacityConflict ? state.device.max_keys : 3, unmapped_notes: 0, merged_notes: 0, retrigger_conflicts: 0, skipped_notes: 0, capacity_conflicts: capacityConflict ? 1 : 0, warnings: unmapped ? [`${unmapped} 个音已按原脚本规则映射`] : [], can_play: true, root_name: 'B', duration_ms: song.duration_ms },
      }
    } else if (endpoint === '/api/music/select') {
      const song = songs.find(song => song.id === data.song_id)!
      state.selected_song_id = song.id; state.current = song.filename; state.revision++; body = state
    } else if (endpoint === '/api/music/play') {
      const song = songs.find(song => song.id === (data.song_id || state.selected_song_id))!
      Object.assign(state, { running: true, paused: false, phase: 'playing', playing_song_id: song.id, playing_name: song.name, position_ms: 0, duration_ms: song.duration_ms, revision: state.revision + 1 })
      commands.push('play'); body = state
    } else if (endpoint === '/api/music/pause') {
      Object.assign(state, { paused: true, phase: 'paused', revision: state.revision + 1 }); commands.push('pause'); body = state
    } else if (endpoint === '/api/music/resume') {
      Object.assign(state, { paused: false, phase: 'playing', revision: state.revision + 1 }); commands.push('resume'); body = state
    } else if (endpoint === '/api/music/stop') {
      if (stopFails) return route.fulfill({ status: 503, json: { detail: { code: 'device_error', message: '设备停止确认失败，请重试' } }, headers: { 'Access-Control-Allow-Origin': '*' } })
      Object.assign(state, { paused: false, running: false, phase: 'stopped', revision: state.revision + 1 }); commands.push('stop'); body = state
    } else if (endpoint === '/api/music/mode') {
      state.mode = data.mode; state.revision++; body = state
    } else throw new Error(`Unhandled music test request ${endpoint}`)
    return route.fulfill({ json: body, headers: { 'Access-Control-Allow-Origin': '*' } })
  })
  if (options.overlay) {
    await page.addInitScript(() => {
      const calls: string[] = []
      ;(window as any).tauriCalls = calls
      ;(window as any).isTauri = true
      ;(window as any).__TAURI_INTERNALS__ = {
        metadata: { currentWindow: { label: 'music_overlay' }, currentWebview: { label: 'music_overlay' } },
        invoke: async (command: string) => { calls.push(command); return null },
      }
    })
  }
  await page.goto('/')
  if (options.overlay) await expect(page.locator('.music-overlay')).toBeVisible()
  else {
    await expect(page.getByRole('heading', { name: '自动演奏', exact: true })).toBeVisible()
    await expect(page.getByRole('checkbox', { name: '音轨 旋律' })).toBeVisible()
  }
  return {
    state, songs, settings, uploads, commands,
    setOnline(value: boolean) { online = value },
    setStopFails(value: boolean) { stopFails = value },
    setDeleteFails(value: boolean) { deleteFails = value },
    update(patch: Partial<typeof state>) { Object.assign(state, patch, { revision: state.revision + 1 }); socket?.send(JSON.stringify({ type: 'event', name: 'music.state', data: state })) },
  }
}

test('imports MIDI bytes, reports each failed file and preserves the legacy library', async ({ page }) => {
  const fixture = await setupMusic(page)
  await page.getByLabel('选择 MIDI 文件').setInputFiles([
    { name: '新曲.mid', mimeType: 'audio/midi', buffer: Buffer.from('MThd-example') },
    { name: '损坏.mid', mimeType: 'audio/midi', buffer: Buffer.from('invalid') },
    { name: '新曲.mid', mimeType: 'audio/midi', buffer: Buffer.from('MThd-example') },
  ])
  await expect(page.getByText('文件不是有效的 MIDI', { exact: true })).toBeVisible()
  await expect(page.getByText('已在曲库中', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '选择曲目 新曲.mid' })).toBeVisible()
  await expect(page.getByRole('button', { name: '选择曲目 旧谱.txt' })).toBeVisible()
  expect(fixture.uploads.map(file => file.contentType)).toEqual(Array(3).fill('application/octet-stream'))
  expect(fixture.uploads.map(file => file.bytes)).toEqual([12, 7, 12])
  const dropFiles = await page.evaluateHandle(() => {
    const transfer = new DataTransfer()
    transfer.items.add(new File(['MThd-dropped'], '拖入.mid', { type: 'audio/midi' }))
    return transfer
  })
  await page.locator('.drop-zone').dispatchEvent('drop', { dataTransfer: dropFiles })
  await expect(page.getByRole('button', { name: '选择曲目 拖入.mid' })).toBeVisible()
  expect(fixture.uploads.at(-1)?.filename).toBe('拖入.mid')
})

test('deletes selected and last songs, supports cancelling and leaves the empty library usable', async ({ page }) => {
  const fixture = await setupMusic(page)
  await page.getByRole('button', { name: '删除曲目 练习和弦.mid' }).click()
  await expect(page.getByRole('group', { name: '删除曲目确认' })).toContainText('电脑中用于导入的原文件会保留')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.getByRole('button', { name: '选择曲目 练习和弦.mid' })).toBeVisible()
  expect(fixture.commands).toEqual([])
  for (const filename of ['练习和弦.mid', '另一首.mid', '旧谱.txt']) {
    await page.getByRole('button', { name: `删除曲目 ${filename}` }).click()
    await page.getByRole('button', { name: '确认删除', exact: true }).click()
    await expect(page.getByRole('button', { name: `选择曲目 ${filename}` })).toHaveCount(0)
  }
  await expect(page.locator('.song-list')).toContainText('导入第一首 MIDI')
  await expect(page.locator('.song-detail')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '播放选中曲目' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '导入 MIDI', exact: true })).toBeEnabled()
  expect(fixture.state.selected_song_id).toBe('')
  expect(fixture.commands).toEqual(['delete:midi-one', 'delete:midi-two', 'delete:txt-one'])
})

test('stops the playing song before deletion and retains it when stopping fails', async ({ page }) => {
  const fixture = await setupMusic(page, { playing: true })
  fixture.setStopFails(true)
  await page.getByRole('button', { name: '删除曲目 练习和弦.mid' }).click()
  await expect(page.getByRole('group', { name: '删除曲目确认' })).toContainText('先停止这首曲目的演奏')
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.locator('.delete-confirmation [role=alert]')).toContainText('设备停止确认失败')
  await expect(page.getByRole('button', { name: '选择曲目 练习和弦.mid' })).toBeVisible()
  expect(fixture.commands).toEqual([])
  fixture.setStopFails(false)
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.getByRole('button', { name: '选择曲目 练习和弦.mid' })).toHaveCount(0)
  expect(fixture.commands).toEqual(['stop', 'delete:midi-one'])
  await expect(page.locator('.now-playing')).toContainText('尚未播放')
})

test('a delayed library refresh cannot restore a song after deletion', async ({ page }) => {
  const fixture = await setupMusic(page)
  let release: () => void = () => {}
  const gate = new Promise<void>(resolve => { release = resolve })
  let requested: () => void = () => {}
  const requestStarted = new Promise<void>(resolve => { requested = resolve })
  await page.route('http://127.0.0.1:8790/api/music/library', async route => {
    const oldLibrary = JSON.stringify({ songs: fixture.songs })
    requested()
    await gate
    await route.fulfill({ body: oldLibrary, contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': '*' } })
  })
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await requestStarted
  await page.getByRole('button', { name: '删除曲目 练习和弦.mid' }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.getByRole('button', { name: '选择曲目 练习和弦.mid' })).toHaveCount(0)
  const response = page.waitForResponse('http://127.0.0.1:8790/api/music/library')
  release()
  await (await response).finished()
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())))
  await expect(page.getByRole('button', { name: '选择曲目 练习和弦.mid' })).toHaveCount(0)
  await expect(page.locator('.detail-heading h3')).toHaveText('另一首')
})

test('deleting another song keeps playback and drafts, and failed deletion can retry', async ({ page }) => {
  const fixture = await setupMusic(page, { playing: true })
  await page.getByLabel('移调（半音）').fill('4')
  fixture.setDeleteFails(true)
  await page.getByRole('button', { name: '删除曲目 旧谱.txt' }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.locator('.delete-confirmation [role=alert]')).toContainText('曲目删除失败')
  await expect(page.getByRole('button', { name: '选择曲目 旧谱.txt' })).toBeVisible()
  fixture.setDeleteFails(false)
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.getByRole('button', { name: '选择曲目 旧谱.txt' })).toHaveCount(0)
  await expect(page.getByLabel('移调（半音）')).toHaveValue('4')
  await expect(page.locator('.now-playing')).toContainText('正在演奏')
  expect(fixture.commands).toEqual(['delete:txt-one'])
})

test('play saves selected tracks and mapping changes automatically', async ({ page }) => {
  const fixture = await setupMusic(page)
  await page.getByRole('checkbox', { name: '音轨 伴奏' }).uncheck()
  await expect(page.getByRole('checkbox', { name: '音轨 鼓', exact: true })).toBeDisabled()
  await page.getByLabel('移调（半音）').fill('2')
  await page.getByLabel('演奏速度', { exact: true }).selectOption('0.75')
  await page.getByLabel('音高映射').selectOption('smooth')
  await page.getByLabel('原曲主调').selectOption('11')
  await expect(page.getByRole('button', { name: '播放选中曲目' })).toBeEnabled()
  await page.getByRole('button', { name: '播放选中曲目' }).click()
  await expect(page.locator('.now-playing')).toContainText('正在演奏')
  expect(fixture.settings.get(midi.id)).toMatchObject({ selected_tracks: [0], transpose: 2, speed: 0.75, root: 11, range_policy: 'smooth', conflict_policy: 'adapt' })
})

test('mapped accidentals and dense notes never require opting into skipping or strict modes', async ({ page }) => {
  const fixture = await setupMusic(page, { unmappedNotes: 4 })
  await expect(page.getByRole('button', { name: '播放选中曲目' })).toBeEnabled()
  await expect(page.getByLabel('音高映射')).toHaveValue('degree')
  await expect(page.getByLabel('无法演奏的音符')).toHaveCount(0)
  await expect(page.locator('.analysis-summary')).toContainText('全部映射演奏')
  await expect(page.locator('.playback-blocked')).toHaveCount(0)
  await page.getByRole('button', { name: '播放选中曲目' }).click()
  await expect(page.locator('.now-playing')).toContainText('正在演奏')
  expect(fixture.commands).toEqual(['play'])
})

test('legacy firmware plays MIDI in single key fallback and also keeps TXT playable', async ({ page }) => {
  await setupMusic(page, { legacyFirmware: true })
  await expect(page.getByText(/当前为单键固件/)).toBeVisible()
  await expect(page.getByRole('button', { name: '播放选中曲目' })).toBeEnabled()
  await page.getByRole('button', { name: '选择曲目 旧谱.txt' }).click()
  await expect(page.getByText('兼容 TXT 按键谱', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '播放选中曲目' })).toBeEnabled()
})

test('selection does not rename the active performance and controls use server state', async ({ page }) => {
  const fixture = await setupMusic(page, { playing: true })
  await expect(page.locator('.now-playing strong')).toHaveText('练习和弦')
  await page.getByRole('button', { name: '暂停', exact: true }).click()
  await expect(page.getByRole('button', { name: '继续演奏', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '继续演奏', exact: true }).click()
  await page.getByRole('button', { name: '选择曲目 另一首.mid' }).click()
  await expect(page.locator('.detail-heading h3')).toHaveText('另一首')
  await expect(page.locator('.now-playing strong')).toHaveText('练习和弦')
  await page.getByRole('button', { name: '播放选中曲目' }).click()
  await expect(page.locator('.now-playing strong')).toHaveText('另一首')
  fixture.update({ position_ms: 15000 })
  await expect(page.getByRole('progressbar', { name: '演奏进度' })).toHaveAttribute('value', '50')
  await page.getByRole('button', { name: '停止', exact: true }).click()
  await expect(page.locator('.now-playing')).toContainText('已停止')
  expect(fixture.commands).toEqual(['pause', 'resume', 'play', 'stop'])
})

test('music connection recovery keeps unsaved adaptation changes', async ({ page }) => {
  const fixture = await setupMusic(page)
  await page.getByLabel('移调（半音）').fill('5')
  fixture.setOnline(false)
  await expect(page.getByText(/连接中断，正在重试：/)).toBeVisible({ timeout: 10000 })
  fixture.setOnline(true)
  await expect(page.getByText(/连接中断，正在重试：/)).toHaveCount(0, { timeout: 10000 })
  await expect(page.getByLabel('移调（半音）')).toHaveValue('5')
  await expect(page.getByRole('button', { name: '播放选中曲目' })).toBeEnabled()
})

test('asynchronous playback errors show their cause from websocket events and polling', async ({ page }) => {
  const fixture = await setupMusic(page, { playing: true })
  fixture.update({ phase: 'error', running: false, error: { code: 'playback_failed', message: 'Arduino 连接失败，请检查设备与端口' } })
  await expect(page.locator('.now-playing')).toContainText('演奏失败')
  await expect(page.getByRole('alert')).toHaveText('Arduino 连接失败，请检查设备与端口')
  Object.assign(fixture.state, { revision: fixture.state.revision + 1, error: { code: 'playback_failed', message: '演奏设备已断开或会话失效' } })
  await expect(page.getByRole('alert')).toHaveText('演奏设备已断开或会话失效', { timeout: 10000 })
  fixture.update({ phase: 'stopped', error: null })
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('delayed initial state restores the selected song and remote selection keeps local drafts', async ({ page }) => {
  const fixture = await setupMusic(page, { selectedId: second.id, stateDelay: 400 })
  await expect(page.locator('.detail-heading h3')).toHaveText('另一首')
  expect(fixture.state.selected_song_id).toBe(second.id)
  await page.getByLabel('移调（半音）').fill('4')
  fixture.update({ selected_song_id: midi.id, current: midi.filename })
  await expect(page.locator('.detail-heading h3')).toHaveText('练习和弦')
  fixture.update({ selected_song_id: second.id, current: second.filename })
  await expect(page.locator('.detail-heading h3')).toHaveText('另一首')
  await expect(page.getByLabel('移调（半音）')).toHaveValue('4')
})

test('device capability changes refresh the analysis without discarding unsaved settings', async ({ page }) => {
  const fixture = await setupMusic(page)
  await expect(page.getByRole('button', { name: '播放选中曲目' })).toBeEnabled()
  fixture.update({ device: { connected: true, protocol: 2, max_keys: 2, midi_supported: true } })
  await expect(page.getByText(/已自动顺延演奏/)).toBeVisible()
  await expect(page.getByRole('button', { name: '播放选中曲目' })).toBeEnabled()
  await page.getByLabel('移调（半音）').fill('3')
  fixture.update({ device: { connected: true, protocol: 2, max_keys: 9, midi_supported: true } })
  await expect(page.getByText(/这份演奏方案暂不可播放/)).toHaveCount(0)
  await expect(page.getByLabel('移调（半音）')).toHaveValue('3')
  await expect(page.getByRole('button', { name: '播放选中曲目' })).toBeEnabled()
  await expect(page.getByRole('button', { name: '保存并重新分析' })).toBeEnabled()
})

test('overlay shows the actual performance and stays open when stopping fails', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 150 })
  const fixture = await setupMusic(page, { overlay: true, playing: true, selectedId: second.id })
  await expect(page.locator('.overlay-heading strong')).toHaveText('练习和弦')
  await expect(page.locator('.sidebar')).toHaveCount(0)
  await page.getByRole('button', { name: '暂停', exact: true }).click()
  await expect(page.getByRole('button', { name: '继续演奏', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '继续演奏', exact: true }).click()
  fixture.update({ position_ms: 30000 })
  await expect(page.getByRole('progressbar', { name: '演奏进度' })).toHaveAttribute('value', '50')
  await page.screenshot({ path: testInfo.outputPath('music-overlay.png') })
  fixture.setStopFails(true)
  await page.getByRole('button', { name: '停止并关闭' }).click()
  await expect(page.locator('.overlay-status')).toHaveText('设备停止确认失败，请重试')
  expect(await page.evaluate(() => (window as any).tauriCalls)).not.toContain('hide_music_overlay')
  fixture.setStopFails(false)
  await page.getByRole('button', { name: '停止并关闭' }).click()
  await expect.poll(() => page.evaluate(() => (window as any).tauriCalls)).toContain('hide_music_overlay')
})

test('music controls remain reachable at supported window sizes', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1120, height: 760 })
  await setupMusic(page)
  await page.screenshot({ path: testInfo.outputPath('music-main.png') })
  await page.locator('.analysis-summary').scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('music-settings.png') })
  await page.setViewportSize({ width: 900, height: 600 })
  await page.getByRole('button', { name: '保存并重新分析' }).scrollIntoViewIfNeeded()
  await expect(page.getByLabel('移调（半音）')).toBeVisible()
  const overflow = await page.locator('.feature-content').evaluate(element => element.scrollWidth > element.clientWidth)
  expect(overflow).toBe(false)
  await page.getByRole('button', { name: '播放选中曲目' }).scrollIntoViewIfNeeded()
  await expect(page.getByRole('button', { name: '播放选中曲目' })).toBeInViewport()
  await page.screenshot({ path: testInfo.outputPath('music-main-small.png') })
})
