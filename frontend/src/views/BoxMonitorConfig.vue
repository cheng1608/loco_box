<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElInputNumber } from 'element-plus/es/components/input-number/index'
import { ElMessage } from 'element-plus/es/components/message/index'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/input-number/style/css'
import 'element-plus/es/components/message/style/css'
import { usePolling } from '../composables/usePolling'
import {
  captureBoxTemplate,
  connectWs,
  getFeatureConfig,
  listFeatures,
  selectRegion,
  setFeatureConfig,
  startFeature,
  stopFeature,
  type Region,
} from '../api/client'

const running = ref(false)
const delay = ref(1)
const threshold = ref(0.45)
const brightness = ref(200)
const triggerDelay = ref(5.0)
const templateRegion = ref<Region | null>(null)
const regionB = ref<Region | null>(null)
const statusText = ref('')

let closeWs: (() => void) | null = null
let unlistenStop: (() => void) | null = null
let disposed = false
const configLoaded = ref(false)

function fmtRegion(r: Region | null) {
  if (!r) return '未设置'
  return `${r.left},${r.top} ${r.width}×${r.height}`
}

async function load() {
  try {
    const { config } = await getFeatureConfig('box_monitor')
    delay.value = Number(config.delay ?? 1)
    threshold.value = Number(config.threshold ?? 0.45)
    brightness.value = Number(config.brightness ?? 200)
    triggerDelay.value = Number(config.trigger_delay ?? 5.0)
    templateRegion.value = (config.template_region as Region) ?? null
    regionB.value = (config.region_b as Region) ?? null
    configLoaded.value = true
    statusText.value = ''
  } catch (error) {
    statusText.value = `配置加载失败，正在重试：${String(error)}`
    return
  }
  // 切换面板会重建组件，重新同步后端真实运行状态
  try {
    const { features } = await listFeatures()
    running.value = features.find((f) => f.id === 'box_monitor')?.running ?? false
  } catch {
    /* 后端未就绪，忽略 */
  }
}
usePolling(async () => { if (!configLoaded.value) await load() }, 2000)

async function save() {
  await setFeatureConfig('box_monitor', {
    delay: String(delay.value),
    threshold: String(threshold.value),
    brightness: String(brightness.value),
    trigger_delay: String(triggerDelay.value),
    template_region: templateRegion.value,
    region_b: regionB.value,
  })
}

async function pickTemplate() {
  try {
    const r = await selectRegion()
    if (r.ok && r.region) {
      templateRegion.value = r.region
      await save()
      // 框选时抓图保存为模板，之后可常态启动监控（盒子不在屏幕也能启动）
      const t = await captureBoxTemplate()
      if (t.valid) {
        ElMessage.success(`监控区已设置 · ${t.stroke_pixels}px 笔画`)
      } else {
        ElMessage.warning('监控区已设置，但模板笔画不足，请在盒子出现时重新框选')
      }
    }
  } catch (e) {
    ElMessage.error(String(e))
  }
}

async function pickRegionB() {
  try {
    const r = await selectRegion()
    if (r.ok && r.region) {
      regionB.value = r.region
      await save()
      ElMessage.success('截图区已设置')
    }
  } catch (e) {
    ElMessage.error(String(e))
  }
}

async function onStart() {
  try {
    await save()
    await startFeature('box_monitor')
    running.value = true
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('show_box_overlay')
    ElMessage.success('监控已启动')
  } catch (e) {
    ElMessage.error(String(e))
  }
}

async function onStop() {
  try {
    await stopFeature('box_monitor')
    running.value = false
  } catch (error) {
    ElMessage.error(String(error))
    return
  }
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('hide_box_overlay')
  } catch {
    /* 非 Tauri 环境忽略 */
  }
}

onMounted(async () => {
  closeWs = connectWs({
    onStatus: (text) => (statusText.value = text),
  })
  // 悬浮窗里点关闭（停止监控）时，同步面板按钮状态
  try {
    const { listen } = await import('@tauri-apps/api/event')
    unlistenStop = await listen('box-monitor-stopped', () => {
      running.value = false
    })
    if (disposed) unlistenStop()
  } catch {
    /* 非 Tauri 环境忽略 */
  }
})

onUnmounted(() => {
  disposed = true
  closeWs?.()
  unlistenStop?.()
})
</script>

<template>
  <div class="panel">
    <h2>惊喜盒子</h2>

    <fieldset :disabled="!configLoaded" class="config-fields">
    <div class="section">
      <h3>区域</h3>
      <div class="region-row">
        <span class="label">监控区</span>
        <span class="coord">{{ fmtRegion(templateRegion) }}</span>
        <el-button size="small" @click="pickTemplate">框选</el-button>
      </div>
      <div class="region-row">
        <span class="label">截图区</span>
        <span class="coord">{{ fmtRegion(regionB) }}</span>
        <el-button size="small" @click="pickRegionB">框选</el-button>
      </div>
    </div>

    <div class="section">
      <h3>参数</h3>
      <div class="param-row">
        <span class="label">截图延时(s)</span>
        <el-input-number v-model="delay" :min="0" :step="1" size="small" />
      </div>
      <div class="param-row">
        <span class="label">匹配阈值</span>
        <el-input-number v-model="threshold" :min="0" :max="1" :step="0.05" size="small" />
      </div>
      <div class="param-row">
        <span class="label">亮度阈值</span>
        <el-input-number v-model="brightness" :min="0" :max="255" :step="1" size="small" />
      </div>
      <div class="param-row">
        <span class="label">触发延时(s)</span>
        <el-input-number v-model="triggerDelay" :min="0" :step="0.5" size="small" />
      </div>
    </div>

    <div class="actions">
      <el-button v-if="!running" type="primary" :disabled="!configLoaded" @click="onStart">开始监控</el-button>
      <el-button v-else type="danger" @click="onStop">停止监控</el-button>
    </div>
    </fieldset>

    <div class="status">{{ statusText }}</div>
  </div>
</template>

<style scoped>
.panel {
  padding: 8px 4px;
}
.config-fields { padding: 0; margin: 0; border: 0; min-width: 0; }
.panel h2 {
  font-size: 16px;
  margin: 0 0 12px;
}
.section {
  margin-bottom: 16px;
}
.section h3 {
  font-size: 13px;
  color: #aaa;
  margin: 0 0 8px;
  font-weight: 500;
}
.region-row,
.param-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.label {
  width: 88px;
  color: #bbb;
  font-size: 13px;
  flex-shrink: 0;
}
.coord {
  color: #8a8a8a;
  font-size: 12px;
  flex: 1;
}
.actions {
  margin: 16px 0;
}
.status {
  color: #9f9f9f;
  font-size: 13px;
}
</style>
