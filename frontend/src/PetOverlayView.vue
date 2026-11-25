<script setup lang="ts">
import { reactive } from 'vue'
import { invoke, isTauri } from '@tauri-apps/api/core'
import PetDetails from './components/PetDetails.vue'
import { petError, usePetViewer } from './composables/usePetViewer'
import { useWindowDrag } from './composables/useWindowDrag'

const viewer = reactive(usePetViewer())
const startDrag = useWindowDrag(cause => { viewer.error = petError(cause) })
async function closeOverlay() {
  if (!isTauri()) return
  try { await invoke('hide_pet_overlay') } catch (cause) { viewer.error = petError(cause) }
}
</script>

<template>
  <section class="pet-overlay">
    <header @mousedown="startDrag"><span class="live-dot" :class="{ active: viewer.active }" /><strong>精灵查看</strong><span class="source" :class="{ demo: viewer.state?.source === '示例回放' }">{{ viewer.state?.source || '实时' }}</span><button aria-label="关闭悬浮窗，继续监听" title="关闭悬浮窗，继续监听" @mousedown.stop @click="closeOverlay">×</button></header>
    <div class="overlay-body">
      <div v-if="(viewer.state?.pets.length ?? 0) > 1" class="pet-tabs"><button v-for="pet in viewer.state?.pets" :key="pet.id" :class="{ selected: String(pet.id) === String(viewer.state?.selected?.id) }" :disabled="viewer.pending" @click="viewer.select(String(pet.id))">{{ pet.name }}</button></div>
      <PetDetails v-if="viewer.state?.selected" :pet="viewer.state.selected" compact />
      <div v-else class="overlay-empty"><span aria-hidden="true">◈</span><strong>{{ viewer.active ? '等待野生遭遇' : '等待开始监听' }}</strong><p>{{ viewer.state?.message || '在主窗口开始监听，再进入游戏世界。' }}</p></div>
    </div>
    <footer><span :class="{ error: viewer.error || viewer.connectionError }" :title="viewer.error || viewer.connectionError || viewer.status">{{ viewer.error || viewer.connectionError || viewer.status }}</span><button v-if="viewer.active" :disabled="!viewer.online" @click="viewer.stop">停止监听</button></footer>
  </section>
</template>

<style scoped>
.pet-overlay { width: 100%; height: 100%; display: flex; flex-direction: column; gap: 8px; padding: 10px; box-sizing: border-box; color: #cad9e9; background: rgba(18, 26, 36, .97); border: 1px solid #486157; border-radius: 13px; overflow: hidden; user-select: none; }.pet-overlay header { display: flex; align-items: center; gap: 7px; flex: 0 0 22px; cursor: grab; padding: 0 3px; }.live-dot { width: 5px; height: 5px; background: #6a7f95; border-radius: 50%; }.live-dot.active { background: #96d5ba; }header strong { font-size: 12px; font-weight: 500; flex: 1; }.source { color: #8ca6be; font-size: 10px; }.source.demo { color: #d9bd87; }button { font: inherit; cursor: pointer; }header button { border: 0; background: transparent; color: #9bb0c5; border-radius: 5px; font-size: 19px; width: 23px; height: 23px; line-height: 20px; }header button:hover { background: #4a2f3b; color: #edb0bf; }.overlay-body { flex: 1; min-height: 0; overflow-y: auto; scrollbar-width: thin; }.overlay-empty { display: flex; height: 100%; min-height: 160px; flex-direction: column; align-items: center; justify-content: center; text-align: center; }.overlay-empty > span { font-size: 34px; color: #638d82; margin-bottom: 12px; }.overlay-empty strong { font-size: 13px; font-weight: 500; }.overlay-empty p { max-width: 270px; color: #8ca1b8; line-height: 1.7; font-size: 11px; }footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex: 0 0 25px; padding: 0 2px; }footer > span { color: #8ba4ba; font-size: 10px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }footer > span.error { color: #efacb8; }footer button { background: #2d3c49; border: 1px solid #425564; border-radius: 5px; color: #b4c7d8; font-size: 10px; padding: 4px 7px; white-space: nowrap; }.pet-tabs { display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 7px; }.pet-tabs button { color: #91a7bd; border: 1px solid #354559; border-radius: 5px; background: #202c3b; font-size: 10px; padding: 4px 7px; }.pet-tabs button.selected { color: #c0e6d5; border-color: #709c8c; }.pet-overlay button:disabled { opacity: .4; cursor: not-allowed; }.pet-overlay button:focus-visible { outline: 2px solid #a5d4bc; outline-offset: 2px; }
</style>
