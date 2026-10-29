<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { usePolling } from './composables/usePolling'
import {
  connectWs,
  getMusicState,
  musicNext,
  musicPause,
  musicPrev,
  musicResume,
  setMusicMode,
  startFeature,
  stopFeature,
} from './api/client'
import {
  PauseIcon,
  PlayIcon,
  RepeatAllIcon,
  RepeatOneIcon,
  SequentialIcon,
  ShuffleIcon,
  SingleIcon,
  SkipNextIcon,
  SkipPrevIcon,
} from './components/MusicIcons'

const running = ref(false)
const paused = ref(false)
const current = ref('')
const mode = ref('sequential')
const statusText = ref('')

const MODES = ['sequential', 'single', 'repeat_one', 'repeat_all', 'shuffle']
const MODE_NAMES: Record<string, string> = {
  sequential: '列表播放',
  single: '单曲播放',
  repeat_one: '单曲循环',
  repeat_all: '列表循环',
  shuffle: '随机播放',
}

let closeWs: (() => void) | null = null

function displayName(name: string) {
  return name.replace(/\.txt$/i, '') || '未选择'
}

const title = computed(() => displayName(current.value))

const modeIcon = computed(() => {
  const map: Record<string, unknown> = {
    sequential: SequentialIcon,
    single: SingleIcon,
    repeat_one: RepeatOneIcon,
    repeat_all: RepeatAllIcon,
    shuffle: ShuffleIcon,
  }
  return map[mode.value] || SequentialIcon
})

const playIcon = computed(() => (running.value && !paused.value ? PauseIcon : PlayIcon))

async function refreshState() {
  try {
    const st = await getMusicState()
    running.value = st.running
    paused.value = st.paused
    current.value = st.current
    mode.value = st.mode
  } catch {
    /* 后端未就绪，忽略 */
  }
}

async function onToggle() {
  try {
    if (!running.value) await startFeature('music')
    else if (paused.value) await musicResume()
    else await musicPause()
  } catch (e) {
    statusText.value = String(e)
  }
  refreshState()
}

async function onNext() {
  try {
    await musicNext()
  } catch (e) {
    statusText.value = String(e)
  }
  refreshState()
}

async function onPrev() {
  try {
    await musicPrev()
  } catch (e) {
    statusText.value = String(e)
  }
  refreshState()
}

async function onMode() {
  const idx = MODES.indexOf(mode.value)
  const next = MODES[(idx + 1) % MODES.length]
  try {
    await setMusicMode(next)
  } catch (e) {
    statusText.value = String(e)
  }
  refreshState()
}

async function closeOverlay() {
  try {
    await stopFeature('music')
  } catch {
    /* ignore */
  }
  try {
    const { emit } = await import('@tauri-apps/api/event')
    await emit('music-overlay-hidden')
  } catch {
    /* 非 Tauri 环境忽略 */
  }
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('hide_music_overlay')
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
  closeWs = connectWs({ onStatus: (t) => (statusText.value = t) })
})
usePolling(refreshState, 800)

onUnmounted(() => {
  closeWs?.()
})
</script>

<template>
  <div class="ctl">
    <div class="topbar" @mousedown="startDrag">
      <span class="title">{{ title }}</span>
      <div class="grip" />
      <button class="close" @mousedown.stop @click="closeOverlay">×</button>
    </div>

    <div class="buttons">
      <button class="icon-btn" title="上一曲" @mousedown.stop @click="onPrev">
        <SkipPrevIcon :size="20" />
      </button>
      <button
        class="icon-btn main"
        :class="{ playing: running && !paused }"
        title="播放/暂停"
        @mousedown.stop
        @click="onToggle"
      >
        <component :is="playIcon" :size="24" />
      </button>
      <button class="icon-btn" title="下一曲" @mousedown.stop @click="onNext">
        <SkipNextIcon :size="20" />
      </button>
      <button
        class="icon-btn"
        :title="`播放模式：${MODE_NAMES[mode] || mode}`"
        @mousedown.stop
        @click="onMode"
      >
        <component :is="modeIcon" :size="20" />
      </button>
    </div>

    <div class="status">{{ statusText || `${MODE_NAMES[mode] || mode}` }}</div>
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
  padding: 8px 10px;
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
.title {
  max-width: 70%;
  color: #ccc;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
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
  flex-shrink: 0;
}
.close:hover {
  background: rgba(245, 108, 108, 0.8);
  color: #fff;
}
.buttons {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
}
.icon-btn {
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.1);
  color: #ccc;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s;
}
.icon-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}
.icon-btn.main {
  width: 48px;
  height: 48px;
  background: rgba(64, 158, 255, 0.92);
  color: #fff;
}
.icon-btn.main.playing {
  background: rgba(245, 108, 108, 0.92);
}
.icon-btn:active {
  transform: scale(0.95);
}
.status {
  height: 16px;
  color: #aaa;
  font-size: 12px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
