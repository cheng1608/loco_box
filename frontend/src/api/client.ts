const BASE = 'http://127.0.0.1:8790'
const WS_URL = 'ws://127.0.0.1:8790/ws'

export interface Status {
  arduino_connected: boolean
  port: string | null
}

export interface Health {
  service: string
  protocol: number
  ready: boolean
}

export class BackendCompatibilityError extends Error {}

export interface FeatureMeta {
  id: string
  name: string
  running: boolean
}

export interface Region {
  left: number
  top: number
  width: number
  height: number
}

async function http<T>(path: string, options?: RequestInit, timeoutMs = 8000): Promise<T> {
  const controller = new AbortController()
  const timer = timeoutMs > 0 ? window.setTimeout(() => controller.abort(), timeoutMs) : undefined
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options?.headers },
      signal: controller.signal,
    })
    if (!res.ok) {
      let detail = `${path} → HTTP ${res.status}`
      try {
        const body = await res.json()
        if (body?.detail) {
          detail = typeof body.detail === 'string' ? body.detail : body.detail.message ?? JSON.stringify(body.detail)
        }
      } catch {
        /* 响应可能没有 JSON 内容。 */
      }
      throw new Error(detail)
    }
    return await res.json()
  } catch (error) {
    if (controller.signal.aborted) throw new Error('本地服务响应超时，请稍后重试')
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

/** 先确认服务身份和协议，避免误连残留的旧进程或其他占用端口的程序。 */
export async function getHealth(): Promise<Health> {
  const health = await http<Health>('/api/health')
  if (health?.service !== 'loco_box' || health.protocol !== 1) {
    throw new BackendCompatibilityError('本地服务版本不兼容：8790 端口正在运行旧版或其他服务。请关闭旧进程后重新启动应用。')
  }
  if (health.ready !== true) throw new Error('本地服务仍在初始化，完成后会自动连接。')
  return health
}

export const getStatus = () => http<Status>('/api/status')

export const connectArduino = (port: string) =>
  http<{ ok: boolean; port: string | null }>('/api/arduino/connect', {
    method: 'POST',
    body: JSON.stringify({ port }),
  }, 30000)

export const disconnectArduino = () =>
  http<{ ok: boolean }>('/api/arduino/disconnect', { method: 'POST' })

export const listFeatures = () => http<{ features: FeatureMeta[] }>('/api/features')

export const getFeatureConfig = (id: string) =>
  http<{ config: Record<string, any> }>(`/api/features/${id}/config`)

export const setFeatureConfig = (id: string, config: Record<string, any>) =>
  http<{ ok: boolean }>(`/api/features/${id}/config`, {
    method: 'PUT',
    body: JSON.stringify({ config }),
  })

export const startFeature = (id: string) =>
  http<{ ok: boolean; running: boolean }>(`/api/features/${id}/start`, { method: 'POST' })

export const stopFeature = (id: string) =>
  http<{ ok: boolean }>(`/api/features/${id}/stop`, { method: 'POST' })

export const selectRegion = () =>
  http<{ ok: boolean; region?: Region; cancelled?: boolean }>('/api/region/select', {
    method: 'POST',
  }, 0) // 框选等待用户操作，不能使用普通 API 的超时。

export const captureBoxTemplate = () =>
  http<{ ok: boolean; valid: boolean; stroke_pixels: number }>(
    '/api/features/box_monitor/template',
    { method: 'POST' },
  )

export const openScoresFolder = () =>
  http<{ ok: boolean }>('/api/music/open_folder', { method: 'POST' })

export interface MusicState {
  playlist: string[]
  current: string
  mode: string
  running: boolean
  paused: boolean
  phase: 'stopped' | 'preparing' | 'countdown' | 'playing' | 'paused' | 'finished' | 'error'
  selected_song_id: string | null
  playing_song_id: string | null
  playing_name: string
  position_ms: number
  duration_ms: number
  speed: number
  countdown_remaining: number
  revision: number
  error: { code: string; message: string } | null
  device: { connected: boolean; protocol: number; max_keys: number; midi_supported: boolean }
}

export interface MusicSong {
  id: string
  name: string
  filename: string
  format: 'midi' | 'txt'
  duration_ms: number
  note_count: number
  track_count: number
  imported_at?: string
  legacy?: boolean
}

export interface MusicSettings {
  selected_tracks: number[] | null
  transpose: number
  range_policy: 'degree' | 'nearest' | 'smooth'
  root: number | null
  conflict_policy: 'adapt'
  mapping_version?: number
  speed: number
  skip_leading_silence: boolean
}

export interface MusicTrack {
  id: number
  name: string
  channels: number[]
  note_count: number
  pitch_min: number | null
  pitch_max: number | null
  percussion: boolean
}

export interface MusicAnalysis {
  source_notes: number
  playable_notes: number
  chord_count: number
  max_keys: number
  unmapped_notes: number
  merged_notes: number
  retrigger_conflicts: number
  skipped_notes: number
  capacity_conflicts: number
  warnings: string[]
  can_play: boolean
  root_name?: string
  repeated_mappings?: number
  retimed_notes?: number
  duration_ms: number
}

export interface MusicSongDetail {
  song: MusicSong
  tracks: MusicTrack[]
  settings: MusicSettings
  analysis: MusicAnalysis
}

export const listMusicLibrary = () => http<{ songs: MusicSong[] }>('/api/music/library', undefined, 30000)
export const deleteMusicSong = (id: string) => http<{ ok: boolean; song_id: string; songs: MusicSong[]; state: MusicState }>(
  `/api/music/songs/${encodeURIComponent(id)}`, { method: 'DELETE' }, 30000,
)
export const importMidi = (file: File) => http<{ song: MusicSong; duplicate: boolean }>(
  `/api/music/import?filename=${encodeURIComponent(file.name)}`,
  { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file }, 60000,
)
export const getMusicSong = (id: string) => http<MusicSongDetail>(`/api/music/songs/${encodeURIComponent(id)}`, undefined, 30000)
export const saveMusicSettings = (id: string, settings: MusicSettings) => http<MusicSongDetail>(
  `/api/music/songs/${encodeURIComponent(id)}/settings`, { method: 'PUT', body: JSON.stringify(settings) }, 30000,
)
export const getMusicState = () => http<MusicState>('/api/music/state')

export const selectSong = (songId: string) =>
  http<MusicState>('/api/music/select', {
    method: 'POST',
    body: JSON.stringify({ song_id: songId }),
  })

export const musicPlay = (songId?: string) => http<MusicState>('/api/music/play', {
  method: 'POST', body: JSON.stringify(songId ? { song_id: songId } : {}),
}, 30000)

export const musicStop = () => http<MusicState>('/api/music/stop', { method: 'POST' }, 15000)
export const musicNext = () => http<MusicState>('/api/music/next', { method: 'POST' }, 30000)
export const musicPrev = () => http<MusicState>('/api/music/prev', { method: 'POST' }, 30000)

export const setMusicMode = (mode: string) =>
  http<MusicState>('/api/music/mode', {
    method: 'POST',
    body: JSON.stringify({ mode }),
  })

export const musicPause = () => http<MusicState>('/api/music/pause', { method: 'POST' })

export const musicResume = () => http<MusicState>('/api/music/resume', { method: 'POST' })

export interface PetDetails {
  id: string
  name: string
  base_id?: number | null
  nature: string
  nature_id?: number | null
  nature_hint: string
  nature_tip: string
  nature_up?: string | null
  nature_down?: string | null
  nature_modified?: boolean
  nature_effective?: string
  bloodline_label: string
  bloodline_tip?: string
  shiny: boolean | null
  shiny_hint?: string
  voice: number | null
  voice_hint: string
  voice_tip?: string
  height: number | null
  height_hint: string
  height_tip?: string
  weight: number | null
  weight_hint: string
  weight_tip?: string
  medal?: string
  complete?: boolean
}

export interface PetViewerState {
  session_id: string
  running: boolean
  phase: string
  status: string
  message: string
  source: string
  revision: number
  resources: { ready: boolean; message: string; version?: string }
  npcap_available: boolean
  packet_count: number
  decoded_count: number
  pets: PetDetails[]
  selected: PetDetails | null
  battle_id?: string | null
  history_error?: string
}

export interface PetAdapter { name: string; description: string }
export interface PetHistoryEntry extends Omit<PetDetails, 'id'> { key: number | string; seen_at: string }

export const getPetViewerState = () => http<PetViewerState>('/api/pet-viewer/state')
export const getPetAdapters = () => http<{ available: boolean; adapters: PetAdapter[]; message: string }>('/api/pet-viewer/adapters')
export const runPetDemo = () => http<PetViewerState>('/api/pet-viewer/demo', { method: 'POST' }, 15000)
export const selectPet = (petId: string) => http<PetViewerState>('/api/pet-viewer/select', {
  method: 'POST', body: JSON.stringify({ pet_id: petId }),
})
export const getPetHistory = (limit = 50, offset = 0) => http<{ items: PetHistoryEntry[]; total: number }>(
  `/api/pet-viewer/history?limit=${limit}&offset=${offset}`,
)

export interface WsHandlers {
  onFrame?: (data: string) => void
  onShot?: (data: string, count: number) => void
  onCount?: (count: number) => void
  onStatus?: (text: string) => void
  onEvent?: (name: string, data: Record<string, unknown>) => void
  onOpen?: () => void
  onClose?: () => void
}

interface WsSubscription {
  handlers: WsHandlers
  preview: boolean
}

// 每个窗口共享一条连接；配置面板只订阅状态，不额外传输整屏图像。
const subscribers = new Set<WsSubscription>()
let socket: WebSocket | null = null
let socketPreview = false
let retryTimer: number | undefined
let retryDelay = 500

function notifySubscribers(notify: (handlers: WsHandlers) => void) {
  for (const { handlers } of subscribers) {
    try {
      notify(handlers)
    } catch (error) {
      console.warn('事件处理失败', error)
    }
  }
}

function syncSocket() {
  window.clearTimeout(retryTimer)
  if (!subscribers.size) {
    const previous = socket
    socket = null
    previous?.close()
    retryDelay = 500
    return
  }
  const preview = Array.from(subscribers).some((sub) => sub.preview)
  if (socket && socketPreview === preview) return
  const previous = socket
  socket = null
  previous?.close()
  socketPreview = preview
  const ws = new WebSocket(`${WS_URL}${preview ? '?preview=1' : ''}`)
  socket = ws
  ws.onopen = () => {
    if (socket !== ws) return
    retryDelay = 500
    notifySubscribers((handlers) => handlers.onOpen?.())
  }
  ws.onmessage = (event) => {
    if (socket !== ws) return
    let msg: any
    try {
      msg = JSON.parse(event.data)
    } catch {
      console.warn('忽略无法解析的服务消息')
      return
    }
    if (!msg || typeof msg.type !== 'string') return
    notifySubscribers((handlers) => {
      if (msg.type === 'frame') handlers.onFrame?.(msg.data)
      else if (msg.type === 'shot') handlers.onShot?.(msg.data, msg.count)
      else if (msg.type === 'count') handlers.onCount?.(msg.count)
      else if (msg.type === 'status') handlers.onStatus?.(msg.text)
      else if (msg.type === 'event') handlers.onEvent?.(msg.name, msg.data)
    })
  }
  ws.onclose = () => {
    if (socket !== ws) return
    socket = null
    notifySubscribers((handlers) => handlers.onClose?.())
    if (subscribers.size) {
      retryTimer = window.setTimeout(syncSocket, retryDelay)
      retryDelay = Math.min(retryDelay * 2, 5000)
    }
  }
  ws.onerror = () => ws.close()
}

/** 订阅窗口共享的 WebSocket，最后一个订阅退出后关闭连接。 */
export function connectWs(handlers: WsHandlers, options: { preview?: boolean } = {}): () => void {
  const subscription = { handlers, preview: options.preview ?? false }
  subscribers.add(subscription)
  syncSocket()
  if (socket?.readyState === WebSocket.OPEN) handlers.onOpen?.()
  return () => {
    subscribers.delete(subscription)
    syncSocket()
  }
}
