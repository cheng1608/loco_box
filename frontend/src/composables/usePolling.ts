import { onMounted, onUnmounted } from 'vue'

/** 每轮请求完成后再计时，避免后端变慢时请求重叠；隐藏窗口暂停轮询。 */
export function usePolling(task: () => Promise<void>, intervalMs: number) {
  let stopped = true
  let pending = false
  let timer: number | undefined

  async function refresh() {
    if (stopped || pending || document.hidden) return
    window.clearTimeout(timer)
    pending = true
    try {
      await task()
    } catch (error) {
      console.warn('状态刷新失败，下次自动重试', error)
    } finally {
      pending = false
      if (!stopped) timer = window.setTimeout(refresh, intervalMs)
    }
  }

  function onVisibilityChange() {
    if (document.hidden) window.clearTimeout(timer)
    else void refresh()
  }

  onMounted(() => {
    stopped = false
    document.addEventListener('visibilitychange', onVisibilityChange)
    void refresh()
  })
  onUnmounted(() => {
    stopped = true
    window.clearTimeout(timer)
    document.removeEventListener('visibilitychange', onVisibilityChange)
  })

  return refresh
}
