<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch, type Component } from 'vue'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElTag } from 'element-plus/es/components/tag/index'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import { isTauri, invoke } from '@tauri-apps/api/core'
import {
  BackendCompatibilityError,
  connectArduino,
  connectWs,
  disconnectArduino,
  getHealth,
  getStatus,
  listFeatures,
  type FeatureMeta,
} from './api/client'
import { usePolling } from './composables/usePolling'
import ViewLoading from './components/ViewLoading.vue'

const features = ref<FeatureMeta[]>([])
const activeId = ref('')
const previewSrc = ref('')
const previewStatus = ref('')
const previewCollapsed = ref(false)
const arduinoConnected = ref(false)
const arduinoPort = ref<string | null>(null)
const backendReady = ref(false)
const loading = ref(false)
const startupError = ref('')
const backendLog = ref('')
const backendFailed = ref(false)
const connectionPending = ref(false)
const pageVisible = ref(!document.hidden)
const featureDescriptions: Record<string, string> = {
  box_monitor: '识别与自动截图',
  throw: '快捷循环操作',
  music: '曲目与演奏控制',
}

function panel(loader: () => Promise<{ default: Component }>) {
  return defineAsyncComponent({ loader, loadingComponent: ViewLoading, errorComponent: ViewLoading, delay: 150 })
}

const panels: Record<string, Component> = {
  box_monitor: panel(() => import('./views/BoxMonitorConfig.vue')),
  throw: panel(() => import('./views/ThrowConfig.vue')),
  music: panel(() => import('./views/MusicConfig.vue')),
}
const activePanel = computed(() => panels[activeId.value] ?? null)

let closeWs: (() => void) | null = null
let disposed = false

async function refreshStatus() {
  loading.value = true
  try {
    // 协议与服务身份通过后，才允许加载配置和启用硬件操作。
    await getHealth()
    if (disposed) return
    const [s, { features: fs }] = await Promise.all([getStatus(), listFeatures()])
    if (disposed) return
    arduinoConnected.value = s.arduino_connected
    arduinoPort.value = s.port
    features.value = fs
    if (!fs.some((f) => f.id === activeId.value)) activeId.value = fs[0]?.id ?? ''
    backendReady.value = true
    startupError.value = ''
    backendLog.value = ''
    backendFailed.value = false
  } catch (error) {
    if (disposed) return
    backendReady.value = false
    backendFailed.value = error instanceof BackendCompatibilityError
    startupError.value = error instanceof Error ? error.message : String(error)
    if (isTauri()) {
      try {
        const state = await invoke<{ phase: string; error: string | null; logPath: string | null }>('backend_status')
        if (disposed) return
        if (state.error) startupError.value = state.error
        backendLog.value = state.logPath ?? ''
        backendFailed.value = backendFailed.value || state.phase === 'failed'
      } catch {
        // 旧版桌面壳仍通过 HTTP 重试恢复。
      }
    }
  } finally {
    if (!disposed) loading.value = false
  }
}
const refresh = usePolling(refreshStatus, 2000)

async function onConnect() {
  connectionPending.value = true
  try {
    const r = await connectArduino('AUTO')
    if (r.ok) ElMessage.success(`已连接 ${r.port}`)
    else ElMessage.error('连接失败')
    await refresh()
  } catch (e) {
    ElMessage.error(String(e))
  } finally {
    connectionPending.value = false
  }
}

async function onDisconnect() {
  connectionPending.value = true
  try {
    await disconnectArduino()
    await refresh()
  } catch (error) {
    ElMessage.error(String(error))
  } finally {
    connectionPending.value = false
  }
}

function connectPreview() {
  closeWs?.()
  const preview = !previewCollapsed.value && pageVisible.value
  closeWs = connectWs({
    onFrame: (data) => {
      previewSrc.value = `data:image/jpeg;base64,${data}`
    },
    onOpen: () => {
      previewStatus.value = '实时预览已连接'
      void refresh()
    },
    onClose: () => {
      previewStatus.value = '实时预览断开，重连中…'
    },
  }, { preview })
}

function onVisibilityChange() {
  pageVisible.value = !document.hidden
}

watch([previewCollapsed, pageVisible], connectPreview)
onMounted(() => {
  connectPreview()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  disposed = true
  closeWs?.()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand-mark" aria-hidden="true">L</div>
      <div class="brand">
        <h1>loco_box</h1>
        <span>游戏助手 · 本地运行</span>
      </div>
      <span class="spacer" />
      <span class="service-state" :class="{ ready: backendReady }">
        <i />{{ backendReady ? '服务已连接' : '服务连接中' }}
      </span>
      <el-tag :type="arduinoConnected ? 'success' : 'info'" size="small">
        {{ arduinoConnected ? `Arduino · ${arduinoPort}` : 'Arduino 未连接' }}
      </el-tag>
      <el-button v-if="!arduinoConnected" size="small" type="primary" :disabled="!backendReady" :loading="connectionPending" @click="onConnect">
        连接 Arduino
      </el-button>
      <el-button v-else size="small" :disabled="!backendReady" :loading="connectionPending" @click="onDisconnect">断开</el-button>
    </header>

    <div class="body">
      <aside class="sidebar">
        <div class="nav-label">工作台</div>
        <button
          v-for="f in features"
          :key="f.id"
          class="feat-btn"
          :class="{ active: f.id === activeId }"
          :aria-label="f.name"
          :aria-pressed="f.id === activeId"
          @click="activeId = f.id"
        >
          <span class="feature-name">{{ f.name }}<i v-if="f.running" class="running-dot" title="运行中" /></span>
          <span class="feature-description">{{ featureDescriptions[f.id] || '功能设置' }}</span>
        </button>
        <div class="sidebar-foot">LOCO BOX <span>WORKSPACE</span></div>
      </aside>

      <main class="content">
        <div v-if="!backendReady" class="connection-state" role="status" aria-live="polite">
          <span class="connection-dot" />
          <div>
            <strong>{{ backendFailed ? '本地服务启动失败' : features.length ? '本地服务连接中断，正在重新连接…' : '正在连接本地服务…' }}</strong>
            <p>{{ backendFailed ? '请查看连接详情和日志，修复后重新启动应用。' : '连接后会自动加载功能，无需关闭或重新启动界面。' }}</p>
            <details v-if="startupError">
              <summary>查看连接详情</summary>
              <p>{{ startupError }}</p>
              <p v-if="backendLog">日志：{{ backendLog }}</p>
            </details>
          </div>
          <el-button size="small" :loading="loading" @click="refresh">立即重试</el-button>
        </div>
        <div v-if="backendReady && !features.length" class="connection-state" role="status">服务已连接，暂无可用功能。</div>
        <div class="feature-content" :inert="!backendReady">
          <component :is="activePanel" />
        </div>
      </main>

      <aside class="preview-panel" :class="{ collapsed: previewCollapsed }">
        <div v-show="!previewCollapsed" class="preview-inner">
          <div class="preview-heading"><strong>实时预览</strong><span>主屏幕</span></div>
          <div class="preview-box">
            <img v-if="previewSrc" :src="previewSrc" alt="屏幕预览" />
            <div v-else class="placeholder">等待预览…</div>
          </div>
          <div class="preview-status">{{ previewStatus }}</div>
        </div>
        <button
          class="collapse-handle"
          :title="previewCollapsed ? '展开预览' : '折叠到右侧'"
          @click="previewCollapsed = !previewCollapsed"
        >
          {{ previewCollapsed ? '◀' : '▶' }}
        </button>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #13171e;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 22px;
  border-bottom: 1px solid #272d38;
  background: #181d26;
}
.brand-mark { width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid #49709b; border-radius: 10px; background: #263d59; color: #bad7fb; font-weight: 700; font-size: 20px; }
.brand { display: flex; flex-direction: column; gap: 3px; }
.brand > span { font-size: 11px; color: #818c9e; }
.service-state { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: #9da6b6; white-space: nowrap; }
.service-state i, .running-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #d5a75c; }
.service-state.ready i, .running-dot { background: #6bbf9a; }
.topbar h1 {
  font-size: 17px;
  letter-spacing: .3px;
  margin: 0;
  color: #fff;
}
.spacer {
  flex: 1;
}
.body {
  flex: 1;
  display: flex;
  overflow: hidden;
}
.sidebar {
  width: 172px;
  flex-shrink: 0;
  border-right: 1px solid #272d38;
  padding: 24px 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #171c24;
}
.nav-label { padding: 0 12px 8px; font-size: 11px; color: #778296; letter-spacing: 2px; }
.sidebar-foot { margin-top: auto; padding: 24px 12px 0; font-size: 10px; letter-spacing: 1px; color: #738096; }
.sidebar-foot span { display: block; margin-top: 4px; color: #4c5769; font-size: 9px; }
.feat-btn {
  text-align: left;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: #b6bfcc;
  cursor: pointer;
  font-size: 14px;
}
.feature-name { display: flex; align-items: center; gap: 8px; font-weight: 500; }
.feature-description { display: block; margin-top: 6px; font-size: 11px; color: #748196; }
.feat-btn:focus-visible, .collapse-handle:focus-visible { outline: 2px solid #79a9e5; outline-offset: 2px; }
.feat-btn:hover {
  background: #202938;
}
.feat-btn.active {
  background: #24344c;
  border-color: #354f72;
  color: #d2e4ff;
}
.feat-btn.active .feature-description { color: #91a8c5; }
.content {
  flex: 1;
  padding: 26px;
  overflow: auto;
  min-width: 0;
}
.connection-state {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 20px;
  margin-bottom: 16px;
  border: 1px solid #30425a;
  border-radius: 12px;
  background: #192332;
  color: #d4e1f3;
  font-size: 13px;
}
.connection-state p { color: #99aac1; line-height: 1.6; margin: 8px 0 0; overflow-wrap: anywhere; }
.connection-state details { margin-top: 12px; }
.connection-state summary { cursor: pointer; color: #99aac1; }
.connection-state > div { flex: 1; min-width: 0; }
.connection-dot { width: 8px; height: 8px; margin-top: 4px; flex-shrink: 0; border-radius: 50%; background: #73a9ee; box-shadow: 0 0 0 5px #263c59; }
.feature-content[inert] { opacity: .5; }
.preview-panel {
  width: 290px;
  flex-shrink: 0;
  border-left: 1px solid #272d38;
  background: #161b23;
  display: flex;
  align-items: stretch;
  overflow: hidden;
  transition: width 0.2s ease;
}
.preview-panel.collapsed {
  width: 30px;
}
.preview-inner {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 22px 0 18px 18px;
}
.preview-heading { display: flex; align-items: center; justify-content: space-between; padding-bottom: 8px; gap: 10px; }
.preview-heading strong { font-size: 12px; font-weight: 500; color: #b8c3d5; }
.preview-heading span { font-size: 10px; color: #6f7c90; }
.collapse-handle {
  width: 30px;
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: #888;
  cursor: pointer;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.collapse-handle:hover {
  background: #232323;
  color: #ccc;
}
.preview-box {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #10151c;
  border: 1px solid #293344;
  border-radius: 10px;
  overflow: hidden;
}
.preview-box img {
  max-width: 100%;
  max-height: 100%;
}
.placeholder {
  color: #69778e;
  font-size: 13px;
}
.preview-status {
  color: #7e8ca2;
  font-size: 11px;
  padding-top: 4px;
}
@media (max-width: 1000px) {
  .sidebar { width: 148px; }
  .preview-panel { width: 230px; }
  .content { padding: 22px 18px; }
  .service-state { display: none; }
}
</style>
