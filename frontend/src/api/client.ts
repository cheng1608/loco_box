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
          detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
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
export const listPorts = () => http<{ ports: string[] }>('/api/ports')

export const connectArduino = (port: string) =>
  http<{ ok: boolean; port: string | null }>('/api/arduino/connect', {
    method: 'POST',
    body: JSON.stringify({ port }),
  }, 30000)

export const disconnectArduino = () =>
  http<{ ok: boolean }>('/api/arduino/disconnect', { method: 'POST' })

export const sendKey = (key: string, holdMs: number) =>
  http<{ ok: boolean }>('/api/key', {
    method: 'POST',
    body: JSON.stringify({ key, hold_ms: holdMs }),
  })

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

export const listScores = () => http<{ scores: string[] }>('/api/music/scores')

export const loadScore = (name: string) =>
  http<{ name: string; content: string }>(
    `/api/music/scores/${encodeURIComponent(name)}`,
  )

export const openScoresFolder = () =>
  http<{ ok: boolean }>('/api/music/open_folder', { method: 'POST' })

export const parseScore = (score: string) =>
  http<{ count: number; notes: { key: string; pause: number }[] }>('/api/music/parse', {
    method: 'POST',
    body: JSON.stringify({ score }),
  })

export interface MusicState {
  playlist: string[]
  current: string
  mode: string
  running: boolean
  paused: boolean
}

export const getMusicState = () => http<MusicState>('/api/music/state')

export const selectSong = (name: string) =>
  http<{ ok: boolean }>('/api/music/select', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })

export const musicNext = () => http<{ ok: boolean }>('/api/music/next', { method: 'POST' })

export const musicPrev = () => http<{ ok: boolean }>('/api/music/prev', { method: 'POST' })

export const setMusicMode = (mode: string) =>
  http<{ ok: boolean }>('/api/music/mode', {
    method: 'POST',
    body: JSON.stringify({ mode }),
  })

export const musicPause = () => http<{ ok: boolean }>('/api/music/pause', { method: 'POST' })

export const musicResume = () => http<{ ok: boolean }>('/api/music/resume', { method: 'POST' })

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
