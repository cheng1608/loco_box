<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElInputNumber } from 'element-plus/es/components/input-number/index'
import { ElMessage } from 'element-plus/es/components/message/index'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/input-number/style/css'
import 'element-plus/es/components/message/style/css'
import { connectWs, getFeatureConfig, setFeatureConfig } from '../api/client'
import { usePolling } from '../composables/usePolling'

const times = reactive({ mouse_hold: 200, mouse_gap: 150, shift_hold: 50, shift_gap: 50 })
const statusText = ref('')
const overlayVisible = ref(false)
let closeWs: (() => void) | null = null
let unlistenOverlay: (() => void) | null = null
let disposed = false
const configLoaded = ref(false)

async function loadConfig() {
  try {
    const { config } = await getFeatureConfig('throw')
    times.mouse_hold = Number(config.mouse_hold ?? 200)
    times.mouse_gap = Number(config.mouse_gap ?? 150)
    times.shift_hold = Number(config.shift_hold ?? 50)
    times.shift_gap = Number(config.shift_gap ?? 50)
    configLoaded.value = true
    statusText.value = ''
  } catch (error) {
    statusText.value = `配置加载失败，正在重试：${String(error)}`
  }
}
usePolling(async () => { if (!configLoaded.value) await loadConfig() }, 2000)

async function onToggleOverlay() {
  try {
    await setFeatureConfig('throw', { ...times })
    const { invoke } = await import('@tauri-apps/api/core')
    overlayVisible.value = await invoke<boolean>('toggle_overlay')
  } catch (e) {
    ElMessage.error(String(e))
  }
}

onMounted(async () => {
  closeWs = connectWs({ onStatus: (t) => (statusText.value = t) })
  // 悬浮窗通过自身关闭按钮关掉时，同步按钮状态
  try {
    const { listen } = await import('@tauri-apps/api/event')
    unlistenOverlay = await listen('overlay-hidden', () => {
      overlayVisible.value = false
    })
    if (disposed) { unlistenOverlay(); return }
  } catch {
    /* 非 Tauri 环境忽略 */
  }
  // 切换面板会重建组件，重新同步悬浮窗真实可见状态
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    overlayVisible.value = await invoke<boolean>('is_overlay_visible')
  } catch {
    /* 非 Tauri 环境忽略 */
  }
})

onUnmounted(() => {
  disposed = true
  closeWs?.()
  unlistenOverlay?.()
})
</script>

<template>
  <div class="panel">
    <h2>丢球</h2>
    <p class="desc">设置四个时间间隔，点「启动」弹出置顶悬浮窗，在悬浮窗里用切换按钮开关丢球。</p>
    <div class="grid">
      <label class="field">
        <span>左键按住(ms)</span>
        <el-input-number v-model="times.mouse_hold" :min="0" :step="10" controls-position="right" />
      </label>
      <label class="field">
        <span>左键后间隔(ms)</span>
        <el-input-number v-model="times.mouse_gap" :min="0" :step="10" controls-position="right" />
      </label>
      <label class="field">
        <span>Shift按住(ms)</span>
        <el-input-number v-model="times.shift_hold" :min="0" :step="10" controls-position="right" />
      </label>
      <label class="field">
        <span>Shift后间隔(ms)</span>
        <el-input-number v-model="times.shift_gap" :min="0" :step="10" controls-position="right" />
      </label>
    </div>
    <div class="actions">
      <el-button :type="overlayVisible ? 'danger' : 'primary'" :disabled="!configLoaded" @click="onToggleOverlay">
        {{ overlayVisible ? '关闭悬浮窗' : '启动' }}
      </el-button>
    </div>
    <div class="status">{{ statusText }}</div>
  </div>
</template>

<style scoped>
.panel {
  padding: 8px 4px;
}
.panel h2 {
  font-size: 16px;
  margin: 0 0 8px;
}
.desc {
  color: #888;
  font-size: 13px;
  margin: 0 0 16px;
}
.grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  max-width: 360px;
}
.field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #bbb;
  font-size: 13px;
}
.field :deep(.el-input-number) {
  width: 120px;
}
.actions {
  margin: 20px 0 12px;
}
.status {
  color: #9f9f9f;
  font-size: 13px;
}
</style>
