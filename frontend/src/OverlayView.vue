<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { listFeatures, startFeature, stopFeature } from './api/client'
import { usePolling } from './composables/usePolling'

const running = ref(false)
const cooldown = ref(0)
let cdTimer: number | undefined

async function refresh() {
  try {
    const { features } = await listFeatures()
    running.value = features.find((f) => f.id === 'throw')?.running ?? false
  } catch {
    /* 后端未就绪，忽略 */
  }
}

function startCooldown() {
  cooldown.value = 5
  if (cdTimer) window.clearInterval(cdTimer)
  cdTimer = window.setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0) {
      window.clearInterval(cdTimer)
      cdTimer = undefined
    }
  }, 1000)
}

async function toggle() {
  if (cooldown.value > 0) return
  try {
    if (running.value) await stopFeature('throw')
    else await startFeature('throw')
  } catch {
    /* ignore */
  }
  refresh()
  startCooldown()
}

async function closeOverlay() {
  try {
    const { emit } = await import('@tauri-apps/api/event')
    await emit('overlay-hidden')
  } catch {
    /* 非 Tauri 环境忽略 */
  }
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('hide_overlay')
  } catch {
    /* ignore */
  }
}

async function startDrag(e: MouseEvent) {
  if (e.button !== 0) return
  try {
    const { getCurrentWindow } = await import('@tauri-apps/api/window')
    await getCurrentWindow().startDragging()
  } catch {
    /* 非 Tauri 环境忽略 */
  }
}

usePolling(refresh, 800)

onUnmounted(() => {
  if (cdTimer) window.clearInterval(cdTimer)
})
</script>

<template>
  <div class="ctl">
    <div class="topbar" @mousedown="startDrag">
      <div class="grip" />
      <span class="title">丢球</span>
      <button class="close" @mousedown.stop @click="closeOverlay">×</button>
    </div>
    <button
      class="btn"
      :class="{ running }"
      :disabled="cooldown > 0"
      @mousedown.stop
      @click="toggle"
    >
      {{ cooldown > 0 ? `冷却中 ${cooldown}s` : running ? '停止丢球' : '丢球' }}
    </button>
  </div>
</template>

<style scoped>
.ctl {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  user-select: none;
  background: rgba(20, 20, 20, 0.95);
  border: 1px solid #2a2a2a;
  border-radius: 10px;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 18px;
}
.grip {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.08);
  cursor: grab;
}
.grip:active {
  cursor: grabbing;
}
.title {
  color: #ccc;
  font-size: 12px;
}
.close {
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.12);
  color: #ccc;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}
.close:hover {
  background: rgba(245, 108, 108, 0.8);
  color: #fff;
}
.btn {
  flex: 1;
  border: none;
  border-radius: 10px;
  font-size: 19px;
  font-weight: 600;
  cursor: pointer;
  color: #fff;
  background: rgba(64, 158, 255, 0.92);
  transition: background 0.15s;
}
.btn.running {
  background: rgba(245, 108, 108, 0.92);
}
.btn:disabled {
  cursor: not-allowed;
  background: rgba(120, 120, 120, 0.6);
  color: #ddd;
}
.btn:not(:disabled):active {
  transform: scale(0.97);
}
</style>
