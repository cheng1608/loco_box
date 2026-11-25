import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  connectWs, getMusicState, musicNext, musicPause, musicPlay, musicPrev,
  musicResume, musicStop, setMusicMode, type MusicState,
} from '../api/client'
import { usePolling } from './usePolling'

export const MUSIC_MODES = ['sequential', 'single', 'repeat_one', 'repeat_all', 'shuffle']
export const MUSIC_MODE_NAMES: Record<string, string> = {
  sequential: '列表播放', single: '单曲播放', repeat_one: '单曲循环', repeat_all: '列表循环', shuffle: '随机播放',
}
export function musicTime(ms: number) {
  const seconds = Math.max(0, Math.floor((ms || 0) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
export function musicName(name: string) { return name.replace(/\.(mid|midi|txt)$/i, '') }
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : String(error) }

export function useMusicPlayer() {
  const state = ref<MusicState | null>(null)
  const online = ref(false)
  const pending = ref(false)
  const error = ref('')
  const connectionError = ref('')
  let disposed = false
  let epoch = 0
  let revision = -1
  let closeWs: (() => void) | undefined
  let commandRevision = 0

  function apply(next: MusicState) {
    if (disposed || !next || typeof next.phase !== 'string') return
    if (typeof next.revision === 'number' && next.revision < revision) return
    revision = next.revision ?? revision
    state.value = next
    online.value = true
  }
  const refresh = usePolling(async () => {
    const currentEpoch = epoch
    try {
      const next = await getMusicState()
      if (!disposed && currentEpoch === epoch) { apply(next); connectionError.value = '' }
    } catch (cause) {
      if (!disposed && currentEpoch === epoch) {
        online.value = false
        revision = -1
        connectionError.value = `连接中断，正在重试：${errorMessage(cause)}`
      }
    }
  }, 1200)

  async function command(action: () => Promise<MusicState>, interrupt = false) {
    if (pending.value && !interrupt) return false
    const request = ++commandRevision
    pending.value = true
    error.value = ''
    try {
      const next = await action()
      if (request === commandRevision) apply(next)
      return true
    } catch (cause) {
      if (!disposed && request === commandRevision) error.value = errorMessage(cause)
      return false
    } finally {
      if (!disposed && request === commandRevision) pending.value = false
    }
  }
  const active = computed(() => state.value?.running ?? false)
  const paused = computed(() => state.value?.phase === 'paused')
  const preparing = computed(() => ['preparing', 'countdown'].includes(state.value?.phase ?? ''))
  const progress = computed(() => Math.min(100, Math.max(0, (state.value?.position_ms ?? 0) / (state.value?.duration_ms || 1) * 100)))
  const status = computed(() => {
    const value = state.value
    if (!online.value) return '正在连接演奏服务…'
    if (value?.error) return '演奏失败'
    if (value?.phase === 'countdown') return `准备开始 · ${Math.ceil(value.countdown_remaining)} 秒`
    return ({ stopped: '已停止', preparing: '正在准备曲目…', playing: '正在演奏', paused: '已暂停', finished: '演奏结束', error: '演奏失败' } as Record<string, string>)[value?.phase ?? ''] ?? '请选择曲目'
  })

  onMounted(() => {
    closeWs = connectWs({
      onEvent(name, data) { if (name === 'music.state') apply(data as unknown as MusicState) },
      onOpen() { epoch++; revision = -1; void refresh() },
      onClose() { epoch++; revision = -1 },
    })
  })
  onUnmounted(() => { disposed = true; closeWs?.() })

  return {
    state, online, pending, error, connectionError, active, paused, preparing, progress, status, refresh, apply, command,
    play: (songId?: string) => command(() => musicPlay(songId)),
    pause: () => command(musicPause), resume: () => command(musicResume), stop: () => command(musicStop, true),
    next: () => command(musicNext), previous: () => command(musicPrev),
    mode: (mode: string) => command(() => setMusicMode(mode)),
  }
}
