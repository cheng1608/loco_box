<script setup lang="ts">
import { defineAsyncComponent } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import ViewLoading from './components/ViewLoading.vue'

type ViewMode = 'main' | 'overlay' | 'box_overlay' | 'music_overlay'

function detectWindow(): ViewMode {
  if (!isTauri()) return 'main'
  try {
    const label = getCurrentWindow().label
    if (label === 'overlay') return 'overlay'
    if (label === 'box_overlay') return 'box_overlay'
    if (label === 'music_overlay') return 'music_overlay'
  } catch {
    /* ignore */
  }
  return 'main'
}

// 必须在首次渲染之前识别窗口，避免每个悬浮窗先挂载一次主界面。
const viewMode = detectWindow()
const views = {
  main: () => import('./MainView.vue'),
  overlay: () => import('./OverlayView.vue'),
  box_overlay: () => import('./BoxOverlayView.vue'),
  music_overlay: () => import('./MusicOverlayView.vue'),
}
const currentView = defineAsyncComponent({
  loader: views[viewMode],
  loadingComponent: ViewLoading,
  errorComponent: ViewLoading,
  delay: 150,
  timeout: 30000,
})
const isOverlay = viewMode !== 'main'
document.documentElement.style.background = isOverlay ? 'transparent' : '#141414'
document.body.style.background = isOverlay ? 'transparent' : '#141414'
if (isOverlay) {
  document.documentElement.style.overflow = 'hidden'
  document.body.style.overflow = 'hidden'
}
</script>

<template>
  <component :is="currentView" />
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
}
body {
  background: #141414;
  color: #e5e5e5;
  font-family: 'Segoe UI', system-ui, sans-serif;
}
</style>
