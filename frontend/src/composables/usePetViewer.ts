import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  connectWs, getPetViewerState, runPetDemo, selectPet, setFeatureConfig,
  startFeature, stopFeature, type PetViewerState,
} from '../api/client'
import { usePolling } from './usePolling'

export function petError(cause: unknown) { return cause instanceof Error ? cause.message : String(cause) }
export function petPercent(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 10) / 10}%` : '—'
}

/** Main panel and overlay use the same state contract and window-shared socket. */
export function usePetViewer() {
  const state = ref<PetViewerState | null>(null)
  const online = ref(false)
  const pending = ref(false)
  const pendingAction = ref('')
  const error = ref('')
  const connectionError = ref('')
  let disposed = false
  let epoch = 0
  let revision = -1
  let session = ''
  const retiredSessions = new Set<string>()
  let commandId = 0
  let commandQueue: Promise<unknown> = Promise.resolve()
  let closeWs: (() => void) | undefined

  function apply(next: PetViewerState) {
    if (disposed || !next || typeof next.phase !== 'string') return
    if (next.session_id && next.session_id !== session) {
      if (retiredSessions.has(next.session_id)) return
      if (session) retiredSessions.add(session)
      session = next.session_id
      revision = -1
    }
    if (typeof next.revision === 'number' && next.revision < revision) return
    revision = next.revision ?? revision
    state.value = next
    online.value = true
    connectionError.value = ''
  }

  const refresh = usePolling(async () => {
    const requestEpoch = epoch
    try {
      const next = await getPetViewerState()
      if (!disposed && requestEpoch === epoch) apply(next)
    } catch (cause) {
      if (!disposed && requestEpoch === epoch) {
        online.value = false
        connectionError.value = `连接中断，正在重试：${petError(cause)}`
      }
    }
  }, 1500)

  async function command(kind: string, action: (isCurrent: () => boolean) => Promise<PetViewerState | null>, interrupt = false) {
    if (pending.value && !interrupt) return false
    const request = ++commandId
    pending.value = true
    pendingAction.value = kind
    error.value = ''
    // A response captured before a command must not overwrite its result.
    epoch++
    try {
      const isCurrent = () => !disposed && request === commandId
      // A stop invalidates any start not yet dispatched, and waits for a start
      // already in flight before sending stop. Requests cannot reopen capture.
      const operation = commandQueue.catch(() => {}).then(() => isCurrent() ? action(isCurrent) : null)
      commandQueue = operation
      const next = await operation
      if (next && isCurrent()) apply(next)
      return next !== null
    } catch (cause) {
      if (!disposed && request === commandId) error.value = petError(cause)
      return false
    } finally {
      if (!disposed && request === commandId) { pending.value = false; pendingAction.value = '' }
    }
  }

  onMounted(() => {
    closeWs = connectWs({
      onEvent(name, data) { if (name === 'pet_viewer.state') apply(data as unknown as PetViewerState) },
      onOpen() { epoch++; revision = -1; void refresh() },
      onClose() { epoch++; revision = -1; online.value = false },
    })
  })
  onUnmounted(() => { disposed = true; epoch++; closeWs?.() })

  return {
    state, online, pending, pendingAction, error, connectionError, apply, refresh,
    active: computed(() => state.value?.running ?? false),
    status: computed(() => online.value ? state.value?.status || '等待开始' : '正在连接精灵查看服务…'),
    start: (adapter: string) => command('start', async (isCurrent) => {
      await setFeatureConfig('pet_viewer', { adapter })
      if (!isCurrent()) return null
      await startFeature('pet_viewer')
      if (!isCurrent()) return null
      return getPetViewerState()
    }),
    stop: () => command('stop', async () => { await stopFeature('pet_viewer'); return getPetViewerState() }, true),
    demo: () => command('demo', runPetDemo),
    select: (id: string) => command('select', () => selectPet(id)),
  }
}
