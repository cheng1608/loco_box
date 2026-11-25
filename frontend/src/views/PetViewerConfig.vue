<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { invoke, isTauri } from '@tauri-apps/api/core'
import { getFeatureConfig, getPetAdapters, getPetHistory, type PetAdapter, type PetHistoryEntry } from '../api/client'
import PetDetails from '../components/PetDetails.vue'
import { petError, usePetViewer } from '../composables/usePetViewer'
import { usePolling } from '../composables/usePolling'

const viewer = reactive(usePetViewer())
const adapter = ref('')
const adapters = ref<PetAdapter[]>([])
const adapterMessage = ref('')
const driverAvailable = ref(false)
const loadingAdapters = ref(false)
const configLoaded = ref(false)
const configError = ref('')
const historyOpen = ref(false)
const history = ref<PetHistoryEntry[]>([])
const historyTotal = ref(0)
const historyOffset = ref(0)
const historyLoading = ref(false)
const historyError = ref('')
let disposed = false
let adapterRequest = 0
let historyRequest = 0

const ready = computed(() => viewer.online && viewer.state?.resources.ready)
const canListen = computed(() => ready.value && configLoaded.value && driverAvailable.value && !loadingAdapters.value)
const demo = computed(() => viewer.state?.source === '示例回放')

async function refreshAdapters() {
  if (loadingAdapters.value) return
  const request = ++adapterRequest
  loadingAdapters.value = true
  try {
    const result = await getPetAdapters()
    if (disposed || request !== adapterRequest) return
    adapters.value = result.adapters
    driverAvailable.value = result.available
    adapterMessage.value = result.message
  } catch (cause) {
    if (!disposed && request === adapterRequest) {
      adapterMessage.value = petError(cause)
      driverAvailable.value = false
    }
  } finally { if (!disposed && request === adapterRequest) loadingAdapters.value = false }
}

async function loadConfig() {
  if (configLoaded.value) return
  try {
    const result = await getFeatureConfig('pet_viewer')
    if (disposed) return
    adapter.value = typeof result.config.adapter === 'string' ? result.config.adapter : ''
    configLoaded.value = true
    configError.value = ''
  } catch (cause) { if (!disposed) configError.value = `配置加载失败，正在重试：${petError(cause)}` }
}
usePolling(loadConfig, 3000)

async function refreshHistory(offset = historyOffset.value) {
  const request = ++historyRequest
  historyLoading.value = true
  try {
    const result = await getPetHistory(20, offset)
    if (disposed || request !== historyRequest) return
    history.value = result.items
    historyTotal.value = result.total
    historyOffset.value = offset
    historyError.value = ''
  } catch (cause) { if (!disposed && request === historyRequest) historyError.value = petError(cause) }
  finally { if (!disposed && request === historyRequest) historyLoading.value = false }
}
usePolling(async () => { if (historyOpen.value && !historyLoading.value) await refreshHistory() }, 6000)

function toggleHistory(event: Event) {
  historyOpen.value = (event.target as HTMLDetailsElement).open
  if (historyOpen.value) void refreshHistory(0)
}
function seenAt(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
async function showOverlay() {
  if (!isTauri()) { viewer.error = '悬浮窗需要在桌面应用中打开'; return }
  try { await invoke('show_pet_overlay') } catch (cause) { viewer.error = petError(cause) }
}
async function openNpcap(event: MouseEvent) {
  event.preventDefault()
  if (!isTauri()) { window.open('https://npcap.com/#download', '_blank', 'noopener,noreferrer'); return }
  try { await invoke('open_npcap_download') } catch (cause) { viewer.error = petError(cause) }
}

onMounted(() => { void refreshAdapters() })
onUnmounted(() => { disposed = true; adapterRequest++; historyRequest++ })
</script>

<template>
  <section class="pet-viewer">
    <header class="page-heading"><div><span class="eyebrow">WILD ENCOUNTERS</span><h2>精灵查看</h2><p>查看野生遭遇的性格、血脉与体型属性。</p></div><button class="secondary" @click="showOverlay">打开悬浮窗</button></header>
    <div class="capture-settings">
      <label for="pet-adapter">监听网卡</label>
      <div class="adapter-row"><select id="pet-adapter" v-model="adapter" :disabled="viewer.active || viewer.pending || !configLoaded">
        <option value="">自动选择可用网卡</option>
        <option v-if="adapter && !adapters.some(item => item.name === adapter)" :value="adapter">已保存的网卡（当前不可用）</option>
        <option v-for="item in adapters" :key="item.name" :value="item.name">{{ item.description || item.name }}</option>
      </select><button class="secondary" :disabled="loadingAdapters || viewer.active || viewer.pending" @click="refreshAdapters">{{ loadingAdapters ? '检查中…' : '刷新网卡' }}</button></div>
      <div class="capture-actions">
        <button v-if="!viewer.active && !['start', 'stop'].includes(viewer.pendingAction)" class="primary" :disabled="!canListen || viewer.pending" @click="viewer.start(adapter)">{{ viewer.pending ? '处理中…' : '开始监听' }}</button>
        <button v-else class="stop" :disabled="!viewer.online || viewer.pendingAction === 'stop'" @click="viewer.stop">{{ viewer.pendingAction === 'stop' ? '正在停止…' : '停止监听' }}</button>
        <button class="secondary" :disabled="!ready || viewer.pending || viewer.active" @click="viewer.demo">示例回放</button>
        <span class="independent-note">无需连接 Arduino</span>
      </div>
      <p class="usage-note">先开始监听，再从登录界面进入游戏世界并遭遇野生精灵。已在游戏中时，请保持监听并重新登录。</p>
    </div>

    <div v-if="viewer.error || viewer.connectionError || configError" class="notice error" role="alert">{{ viewer.error || viewer.connectionError || configError }}</div>
    <div v-if="viewer.state && !viewer.state.resources.ready" class="notice error" role="alert">{{ viewer.state.resources.message || '协议资源尚未就绪，请检查资源文件。' }}</div>
    <div v-if="!loadingAdapters && !driverAvailable" class="notice driver-notice">
      <strong>实时监听暂不可用</strong><p>{{ adapterMessage || '尚未检测到 Npcap，请安装后刷新网卡。' }}</p>
      <a href="https://npcap.com/#download" target="_blank" rel="noopener noreferrer" @click="openNpcap">打开 Npcap 官方下载页 ↗</a>
      <span>可先使用示例回放查看效果。</span>
    </div>
    <p v-else-if="adapterMessage" class="adapter-note">{{ adapterMessage }}</p>

    <div class="encounter-heading"><span class="capture-status" :class="{ active: viewer.active, ended: viewer.state?.phase === 'ended' }"><i />{{ viewer.status }}</span><span class="source-badge" :class="{ demo }">{{ viewer.state?.source || '实时' }}</span></div>
    <div v-if="demo" class="demo-banner">当前显示合成示例数据，不代表真实遭遇，也不会写入历史记录。</div>
    <div v-if="(viewer.state?.pets.length ?? 0) > 1" class="pet-tabs" aria-label="当前遭遇精灵">
      <button v-for="pet in viewer.state?.pets" :key="pet.id" :class="{ selected: String(viewer.state?.selected?.id) === String(pet.id) }" :aria-pressed="String(viewer.state?.selected?.id) === String(pet.id)" :disabled="viewer.pending" @click="viewer.select(String(pet.id))">{{ pet.name }}</button>
    </div>
    <PetDetails v-if="viewer.state?.selected" :pet="viewer.state.selected" />
    <div v-else class="empty-encounter"><div aria-hidden="true">◈</div><strong>{{ viewer.active ? '等待野生精灵出现' : '准备查看下一次遭遇' }}</strong><p>{{ viewer.state?.message || '开启监听后，在这里查看精灵的原始性格与属性。' }}</p></div>
    <p v-if="viewer.state?.selected && viewer.state.message" class="encounter-message">{{ viewer.state.message }}</p>
    <p class="field-note">未下发的属性显示“—”或“未知”；仅显示已确认的野生交互 PVE。悬停数值可查看详情。</p>
    <div v-if="viewer.state?.history_error" class="notice error">{{ viewer.state.history_error }}</div>

    <details class="history-section" @toggle="toggleHistory">
      <summary>本机遭遇记录 <span>{{ historyTotal ? `${historyTotal} 条` : '' }}</span></summary>
      <div class="history-toolbar"><span>只记录实时读取的野生遭遇</span><button class="secondary" :disabled="historyLoading" @click="refreshHistory(0)">刷新记录</button></div>
      <p v-if="historyError" class="history-error" role="alert">{{ historyError }}</p>
      <div v-if="history.length" class="history-scroll"><table><thead><tr><th>精灵</th><th>性格</th><th>遇见时间</th></tr></thead><tbody><tr v-for="item in history" :key="item.key"><td><strong>{{ item.name }}</strong><small>{{ item.bloodline_label }}</small></td><td :title="item.nature_tip">{{ item.nature }}<small>{{ item.nature_hint }}</small></td><td>{{ seenAt(item.seen_at) }}</td></tr></tbody></table></div>
      <p v-else class="history-empty">{{ historyLoading ? '正在读取记录…' : '暂无记录，真实遭遇会自动保存在本机。' }}</p>
      <div v-if="historyTotal > 20" class="pagination"><button class="secondary" :disabled="historyLoading || historyOffset === 0" @click="refreshHistory(Math.max(0, historyOffset - 20))">上一页</button><span>{{ Math.floor(historyOffset / 20) + 1 }} / {{ Math.ceil(historyTotal / 20) }}</span><button class="secondary" :disabled="historyLoading || historyOffset + 20 >= historyTotal" @click="refreshHistory(historyOffset + 20)">下一页</button></div>
    </details>
  </section>
</template>

<style scoped>
.pet-viewer { max-width: 920px; margin: 0 auto; color: #d2ddea; }.page-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 24px; }.eyebrow { color: #8abeb0; font-size: 10px; letter-spacing: 1.8px; }.page-heading h2 { margin: 5px 0 7px; font-size: 25px; font-weight: 600; }.page-heading p { margin: 0; color: #91a0b4; font-size: 12px; }.pet-viewer button { border: 1px solid #374659; border-radius: 7px; padding: 8px 12px; font: inherit; font-size: 12px; cursor: pointer; color: #c3d0e2; white-space: nowrap; }.pet-viewer button:disabled { opacity: .45; cursor: not-allowed; }.pet-viewer button:not(:disabled):hover { filter: brightness(1.14); }.pet-viewer button:focus-visible, select:focus-visible { outline: 2px solid #9bd5c0; outline-offset: 2px; }.secondary { background: #232d3c; }.primary { background: #8dcab3; color: #132a22 !important; border-color: #8dcab3 !important; font-weight: 600 !important; }.stop { background: #583638; color: #ffd2cf !important; border-color: #875454 !important; }.capture-settings { border: 1px solid #2c394b; padding: 16px; border-radius: 12px; background: #171f2a; }.capture-settings label { display: block; color: #b4c2d3; font-size: 12px; margin-bottom: 8px; }.adapter-row { display: flex; gap: 8px; }.adapter-row select { flex: 1; min-width: 0; border: 1px solid #3a485c; border-radius: 7px; padding: 8px 10px; color: #d2deed; background: #1d2735; font-size: 12px; }.capture-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 13px; }.independent-note { margin-left: auto; color: #7e968e; font-size: 11px; }.usage-note { margin: 13px 0 0; line-height: 1.7; color: #8193aa; font-size: 11px; }.notice { margin-top: 12px; border: 1px solid #65533b; padding: 12px 14px; border-radius: 9px; color: #cfb996; background: #302a22; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }.notice.error { background: #35262b; border-color: #70434c; color: #f0acb9; }.driver-notice strong { font-weight: 500; }.driver-notice p { margin: 3px 0 5px; }.driver-notice a { color: #dac38f; margin-right: 15px; }.driver-notice span { display: inline-block; color: #9e9481; font-size: 11px; }.adapter-note { font-size: 11px; color: #91a0b4; }
.encounter-heading { display: flex; align-items: center; justify-content: space-between; margin: 22px 0 12px; }.capture-status { display: flex; align-items: center; gap: 7px; color: #a4b5ca; font-size: 12px; }.capture-status i { width: 6px; height: 6px; background: #6e7f93; border-radius: 50%; }.capture-status.active i { background: #91d5b9; box-shadow: 0 0 0 3px #91d5b912; }.source-badge { border: 1px solid #3a4c61; border-radius: 4px; padding: 2px 6px; color: #90accb; font-size: 10px; }.source-badge.demo { color: #ddc08a; border-color: #6b573b; }.demo-banner { margin-bottom: 12px; color: #c8b48f; font-size: 11px; line-height: 1.6; }.pet-tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }.pet-tabs button { background: #202c3c; }.pet-tabs button.selected { border-color: #8abeb0; color: #b4e0d1; background: #283b36; }.empty-encounter { border: 1px dashed #344257; border-radius: 14px; min-height: 190px; padding: 24px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }.empty-encounter > div { font-size: 34px; color: #547f77; margin-bottom: 11px; }.empty-encounter strong { font-size: 14px; font-weight: 500; color: #b7c7dc; }.empty-encounter p { max-width: 400px; color: #8295ad; font-size: 12px; line-height: 1.8; }.field-note, .encounter-message { color: #7e91a9; font-size: 11px; line-height: 1.7; margin: 10px 0 0; }.history-section { border-top: 1px solid #2f3b4d; margin-top: 24px; padding-top: 15px; }.history-section summary { font-size: 13px; cursor: pointer; color: #b7c7da; }.history-section summary span { color: #7e91a9; font-size: 11px; margin-left: 8px; }.history-toolbar { display: flex; justify-content: space-between; align-items: center; margin: 14px 0; gap: 10px; color: #8499b2; font-size: 11px; }.history-empty { font-size: 12px; color: #8194ac; padding: 12px 0; }.history-error { color: #f0acb9; font-size: 12px; }.history-scroll { overflow-x: auto; }table { width: 100%; border-collapse: collapse; text-align: left; font-size: 12px; }th { font-size: 11px; font-weight: 500; color: #8498b1; padding: 9px 10px; }td { padding: 10px; border-top: 1px solid #293648; vertical-align: top; }td strong { font-weight: 500; }td small { display: block; margin-top: 5px; color: #879bb4; font-size: 10px; }td:last-child { font-size: 11px; color: #8a9fb7; white-space: nowrap; }.pagination { display: flex; align-items: center; justify-content: flex-end; gap: 10px; padding-top: 12px; font-size: 11px; color: #90a3ba; }@media(max-width: 800px) { .page-heading { align-items: flex-start; }.page-heading > button { padding: 7px; font-size: 11px; }.independent-note { margin-left: 0; }.capture-settings { padding: 12px; } }
</style>
