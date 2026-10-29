<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { connectWs, stopFeature } from './api/client'

const boxCount = ref(0)
const shotPreview = ref('')
const statusText = ref('')
let closeWs: (() => void) | null = null

async function closeAndStop() {
  try {
    await stopFeature('box_monitor')
  } catch {
    /* ignore */
  }
  try {
    const { emit } = await import('@tauri-apps/api/event')
    await emit('box-monitor-stopped')
  } catch {
    /* 非 Tauri 环境忽略 */
  }
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('hide_box_overlay')
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

onMounted(() => {
  closeWs = connectWs({
    onShot: (data, count) => {
      shotPreview.value = `data:image/jpeg;base64,${data}`
      boxCount.value = count
    },
    onCount: (count) => {
      boxCount.value = count
    },
    onStatus: (text) => (statusText.value = text),
  })
})

onUnmounted(() => closeWs?.())
</script>

<template>
  <div class="box">
    <div class="topbar" @mousedown="startDrag">
      <div class="grip" />
      <span class="title">惊喜盒子</span>
      <button class="close" @mousedown.stop @click="closeAndStop">×</button>
    </div>
    <div class="count">
      <span class="num">{{ boxCount }}</span>
      <span class="label">已记录</span>
    </div>
    <div class="shot">
      <img v-if="shotPreview" :src="shotPreview" alt="截图" />
      <div v-else class="placeholder">{{ statusText || '等待截图…' }}</div>
    </div>
  </div>
</template>

<style scoped>
.box {
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
.count {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.num {
  font-size: 26px;
  font-weight: 700;
  color: #409eff;
}
.label {
  color: #aaa;
  font-size: 13px;
}
.shot {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #1c1c1c;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  overflow: hidden;
}
.shot img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.placeholder {
  color: #555;
  font-size: 13px;
}
</style>
