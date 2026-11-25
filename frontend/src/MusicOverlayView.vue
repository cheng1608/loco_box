<script setup lang="ts">
import { computed, reactive, type Component } from 'vue'
import { isTauri, invoke } from '@tauri-apps/api/core'
import { emit } from '@tauri-apps/api/event'
import { useWindowDrag } from './composables/useWindowDrag'
import { MUSIC_MODES, MUSIC_MODE_NAMES, musicName, musicTime, useMusicPlayer } from './composables/useMusicPlayer'
import { PauseIcon, PlayIcon, SkipNextIcon, SkipPrevIcon, RepeatAllIcon, RepeatOneIcon, SequentialIcon, ShuffleIcon, SingleIcon } from './components/MusicIcons'

const player = reactive(useMusicPlayer())
const startDrag = useWindowDrag(cause => { player.error = String(cause) })
const title = computed(() => musicName(player.state?.playing_name || player.state?.current || '') || '未选择曲目')
const modeIcons: Record<string, Component> = { sequential: SequentialIcon, single: SingleIcon, repeat_one: RepeatOneIcon, repeat_all: RepeatAllIcon, shuffle: ShuffleIcon }
const modeIcon = computed(() => modeIcons[player.state?.mode ?? 'sequential'] ?? SequentialIcon)
const canPlay = computed(() => player.online && !player.pending && !player.preparing && !!(player.state?.selected_song_id || player.state?.playing_song_id))
async function toggle() {
  if (player.paused) await player.resume()
  else if (player.active) await player.pause()
  else await player.play()
}
async function cycleMode() {
  const index = MUSIC_MODES.indexOf(player.state?.mode ?? 'sequential')
  await player.mode(MUSIC_MODES[(index + 1) % MUSIC_MODES.length])
}
async function closeOverlay() {
  // Keep the window visible if stopping fails, so a failed release is not hidden.
  if (!await player.stop()) return
  if (!isTauri()) return
  try {
    await emit('music-overlay-hidden')
    await invoke('hide_music_overlay')
  } catch (cause) { player.error = String(cause) }
}
</script>

<template>
  <section class="music-overlay">
    <div class="overlay-heading" @mousedown="startDrag">
      <span class="live-dot" :class="{ active: player.active }" />
      <strong :title="title">{{ title }}</strong>
      <button class="close" title="停止并关闭" aria-label="停止并关闭" @mousedown.stop @click="closeOverlay">×</button>
    </div>
    <div class="overlay-controls">
      <button title="上一曲" aria-label="上一曲" :disabled="!player.online || player.pending" @mousedown.stop @click="player.previous"><SkipPrevIcon :size="19" /></button>
      <button class="play" :title="player.paused ? '继续演奏' : player.active ? '暂停' : '播放'" :aria-label="player.paused ? '继续演奏' : player.active ? '暂停' : '播放'" :disabled="!canPlay" @mousedown.stop @click="toggle"><PauseIcon v-if="player.active && !player.paused" :size="23" /><PlayIcon v-else :size="23" /></button>
      <button title="停止" aria-label="停止" :disabled="!player.online || (!player.active && !player.pending)" @mousedown.stop @click="player.stop"><span class="stop-icon" /></button>
      <button title="下一曲" aria-label="下一曲" :disabled="!player.online || player.pending" @mousedown.stop @click="player.next"><SkipNextIcon :size="19" /></button>
      <button :title="MUSIC_MODE_NAMES[player.state?.mode ?? 'sequential']" aria-label="切换播放模式" :disabled="!player.online || player.pending" @mousedown.stop @click="cycleMode"><component :is="modeIcon" :size="18" /></button>
    </div>
    <div class="timeline"><span>{{ musicTime(player.state?.position_ms ?? 0) }}</span><progress max="100" :value="player.progress" aria-label="演奏进度" /><span>{{ musicTime(player.state?.duration_ms ?? 0) }}</span></div>
    <div class="overlay-status" :class="{ error: player.error || player.connectionError || player.state?.error }" :title="player.error || player.connectionError || player.state?.error?.message || player.status" aria-live="polite">{{ player.error || player.connectionError || player.state?.error?.message || player.status }}</div>
  </section>
</template>

<style scoped>
.music-overlay { width: 100%; height: 100%; box-sizing: border-box; display: flex; flex-direction: column; gap: 6px; padding: 10px 12px 9px; overflow: hidden; user-select: none; background: rgba(20, 27, 38, .97); border: 1px solid #3b4e68; border-radius: 12px; color: #ceddef; font-family: 'Segoe UI', system-ui, sans-serif; }
.overlay-heading { display: flex; align-items: center; gap: 7px; height: 19px; cursor: grab; }.overlay-heading strong { flex: 1; min-width: 0; font-size: 12px; font-weight: 500; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }.live-dot { width: 5px; height: 5px; border-radius: 50%; background: #64748b; }.live-dot.active { background: #83cdb0; }.close { width: 21px; height: 21px; border: 0; border-radius: 6px; background: transparent; color: #899eb9; cursor: pointer; font-size: 18px; }.close:hover { background: #4a2f3b; color: #f1a5b3; }
.overlay-controls { display: flex; align-items: center; justify-content: center; gap: 9px; flex: 1; min-height: 42px; }.overlay-controls button { display: grid; place-items: center; border: 0; border-radius: 50%; width: 33px; height: 33px; background: #2b3a50; color: #c1d3e9; cursor: pointer; }.overlay-controls button.play { width: 42px; height: 42px; background: #78ace8; color: #102238; }.overlay-controls button:hover { filter: brightness(1.15); }.overlay-controls button:disabled { opacity: .4; cursor: not-allowed; }.stop-icon { width: 11px; height: 11px; border-radius: 2px; background: currentColor; }.timeline { display: flex; align-items: center; gap: 8px; font-size: 9px; color: #7f98b7; }.timeline progress { appearance: none; flex: 1; min-width: 0; height: 3px; border: 0; border-radius: 4px; background: #32435b; overflow: hidden; }.timeline progress::-webkit-progress-bar { background: #32435b; }.timeline progress::-webkit-progress-value { background: #83b5ed; }.overlay-status { height: 15px; font-size: 10px; color: #91aac8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: center; }.overlay-status.error { color: #f0abb2; }button:focus-visible { outline: 2px solid #b2d5ff; outline-offset: 2px; }
</style>
