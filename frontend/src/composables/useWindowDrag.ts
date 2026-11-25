import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

/** Only a primary-button drag in the desktop shell can move an overlay. */
export function useWindowDrag(onError: (error: unknown) => void = console.warn) {
  return async (event: MouseEvent) => {
    if (event.button !== 0 || !isTauri()) return
    try {
      await getCurrentWindow().startDragging()
    } catch (error) {
      onError(error)
    }
  }
}
