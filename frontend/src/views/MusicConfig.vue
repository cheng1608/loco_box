<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElButton } from 'element-plus/es/components/button/index'
import 'element-plus/es/components/button/style/css'
import { isTauri, invoke } from '@tauri-apps/api/core'
import {
  deleteMusicSong, getMusicSong, importMidi, listMusicLibrary, openScoresFolder, saveMusicSettings, selectSong,
  type MusicSettings, type MusicSong, type MusicSongDetail,
} from '../api/client'
import { errorMessage, MUSIC_MODES, MUSIC_MODE_NAMES, musicName, musicTime, useMusicPlayer } from '../composables/useMusicPlayer'

const player = reactive(useMusicPlayer())
const songs = ref<MusicSong[]>([])
const selectedId = ref('')
const detail = ref<MusicSongDetail | null>(null)
const draft = ref<MusicSettings | null>(null)
const loadingLibrary = ref(false)
const loadingDetail = ref(false)
const saving = ref(false)
const importing = ref(false)
const deleting = ref(false)
const deleteTarget = ref<MusicSong | null>(null)
const deleteError = ref('')
const dragging = ref(false)
const libraryError = ref('')
const detailError = ref('')
const importResults = ref<{ name: string; message: string; ok: boolean }[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const settingsSection = ref<HTMLElement | null>(null)
const analyzedDevice = ref('')
const drafts = new Map<string, MusicSettings>()
let disposed = false
let detailRequest = 0
let libraryRequest = 0
let selectionQueue: Promise<unknown> = Promise.resolve()

const cloneSettings = (settings: MusicSettings): MusicSettings => ({ ...settings, selected_tracks: settings.selected_tracks ? [...settings.selected_tracks] : null })
const dirty = computed(() => !!detail.value && !!draft.value && JSON.stringify(draft.value) !== JSON.stringify(detail.value.settings))
const selectedSong = computed(() => songs.value.find(song => song.id === selectedId.value))
const oldFirmware = computed(() => selectedSong.value?.format === 'midi' && player.state?.device.connected && !player.state.device.midi_supported)
const canPlay = computed(() => player.online && !!detail.value && !loadingDetail.value && !saving.value)
const selectedIsPlaying = computed(() => player.active && player.state?.playing_song_id === selectedId.value)
const playbackBlockReason = computed(() => {
  if (!player.online) return '正在连接演奏服务，连接恢复后可播放。'
  if (player.preparing) return '正在准备演奏，倒计时结束后可暂停；需要取消时请点停止。'
  if (selectedIsPlaying.value) return ''
  if (loadingDetail.value) return '正在分析选中曲目，请稍候。'
  if (saving.value) return '正在保存设置并重新分析，请稍候。'
  if (detailError.value) return `曲目分析失败：${detailError.value}`
  if (!detail.value) return '请先从曲库选择一首曲目。'
  return ''
})
const selectedTrackCount = computed(() => detail.value?.tracks.filter(track => track.note_count && !track.percussion && (draft.value?.selected_tracks === null || draft.value?.selected_tracks.includes(track.id))).length ?? 0)
const playingTitle = computed(() => musicName(player.state?.playing_name || '') || '尚未播放')
const deviceSignature = computed(() => {
  const device = player.state?.device
  return device ? `${device.connected}:${device.protocol}:${device.max_keys}` : ''
})

function chooseInitialSong() {
  if (selectedId.value || !player.state) return
  const initial = songs.value.find(song => song.id === player.state?.selected_song_id) ?? songs.value[0]
  if (initial) void pickSong(initial, initial.id !== player.state.selected_song_id)
}

async function refreshLibrary() {
  if (deleting.value) return
  const request = ++libraryRequest
  loadingLibrary.value = true
  libraryError.value = ''
  try {
    const result = await listMusicLibrary()
    if (disposed || request !== libraryRequest) return
    songs.value = result.songs
    if (!selectedId.value) chooseInitialSong()
    else if (!result.songs.some(song => song.id === selectedId.value)) {
      detail.value = null
      draft.value = null
      selectedId.value = ''
      chooseInitialSong()
    }
  } catch (cause) {
    if (!disposed && request === libraryRequest) libraryError.value = errorMessage(cause)
  } finally {
    if (!disposed && request === libraryRequest) loadingLibrary.value = false
  }
}

async function pickSong(song: MusicSong, notifySelection = true) {
  if (saving.value || deleting.value) return
  if (detail.value && draft.value) drafts.set(detail.value.song.id, cloneSettings(draft.value))
  const request = ++detailRequest
  const requestedDevice = deviceSignature.value
  selectedId.value = song.id
  detail.value = null
  draft.value = null
  loadingDetail.value = true
  detailError.value = ''
  // Selection commands remain ordered when users rapidly click different songs.
  const selection = notifySelection ? selectionQueue.catch(() => {}).then(() => selectSong(song.id)) : Promise.resolve(null)
  if (notifySelection) selectionQueue = selection
  try {
    const [result, state] = await Promise.all([getMusicSong(song.id), selection])
    if (disposed || request !== detailRequest) return
    if (state) player.apply(state)
    analyzedDevice.value = requestedDevice
    detail.value = result
    draft.value = cloneSettings(drafts.get(song.id) ?? result.settings)
  } catch (cause) {
    if (!disposed && request === detailRequest) detailError.value = errorMessage(cause)
  } finally {
    if (!disposed && request === detailRequest) loadingDetail.value = false
  }
}

async function saveSettings() {
  if (!detail.value || !draft.value || saving.value || deleting.value) return false
  saving.value = true
  detailError.value = ''
  const songId = detail.value.song.id
  try {
    const result = await saveMusicSettings(songId, cloneSettings(draft.value))
    if (disposed || songId !== selectedId.value) return
    detail.value = result
    draft.value = cloneSettings(result.settings)
    drafts.delete(songId)
    return true
  } catch (cause) {
    if (!disposed) detailError.value = errorMessage(cause)
    return false
  } finally { if (!disposed) saving.value = false }
}

function trackSelected(id: number) { return draft.value?.selected_tracks === null || !!draft.value?.selected_tracks.includes(id) }
function toggleTrack(id: number, event: Event) {
  if (!draft.value || !detail.value) return
  const chosen = new Set(draft.value.selected_tracks ?? detail.value.tracks.filter(track => !track.percussion && track.note_count > 0).map(track => track.id))
  if ((event.target as HTMLInputElement).checked) chosen.add(id)
  else chosen.delete(id)
  draft.value.selected_tracks = [...chosen].sort((a, b) => a - b)
}

async function importFiles(files: File[]) {
  if (importing.value || deleting.value || !files.length) return
  importing.value = true
  importResults.value = []
  for (const file of files) {
    if (disposed) break
    if (!/\.(mid|midi)$/i.test(file.name)) {
      importResults.value.push({ name: file.name, message: '请选择 .mid 或 .midi 文件', ok: false })
      continue
    }
    try {
      const result = await importMidi(file)
      if (!disposed) importResults.value.push({ name: file.name, message: result.duplicate ? '已在曲库中' : '导入成功', ok: true })
    } catch (cause) {
      if (!disposed) importResults.value.push({ name: file.name, message: errorMessage(cause), ok: false })
    }
  }
  if (!disposed) { importing.value = false; await refreshLibrary() }
}
function onFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  void importFiles(files)
}
function onDrop(event: DragEvent) {
  dragging.value = false
  void importFiles(Array.from(event.dataTransfer?.files ?? []))
}
function requestDelete(song: MusicSong) {
  deleteTarget.value = song
  deleteError.value = ''
}
async function confirmDelete() {
  const song = deleteTarget.value
  if (!song || deleting.value) return
  deleting.value = true
  libraryRequest++
  loadingLibrary.value = false
  deleteError.value = ''
  try {
    // Let an already-sent selection settle before removing its target.
    await selectionQueue.catch(() => {})
    if (player.active && player.state?.playing_song_id === song.id) {
      if (!await player.stop()) throw new Error(player.error || '演奏停止失败，请重试')
    }
    const result = await deleteMusicSong(song.id)
    if (disposed) return
    drafts.delete(song.id)
    if (selectedId.value === song.id) {
      detailRequest++
      selectedId.value = ''
      detail.value = null
      draft.value = null
      loadingDetail.value = false
      detailError.value = ''
    }
    songs.value = result.songs
    player.apply(result.state)
    deleteTarget.value = null
  } catch (cause) {
    if (!disposed) deleteError.value = errorMessage(cause)
  } finally {
    if (!disposed) {
      deleting.value = false
      chooseInitialSong()
    }
  }
}
async function openFolder() {
  try { await openScoresFolder() } catch (cause) { libraryError.value = errorMessage(cause) }
}
async function showOverlay() {
  if (!isTauri()) { libraryError.value = '悬浮窗需要在桌面应用中打开'; return }
  try { await invoke('show_music_overlay') } catch (cause) { libraryError.value = errorMessage(cause) }
}
async function togglePlayback() {
  if (selectedIsPlaying.value) {
    if (player.paused) await player.resume()
    else if (!player.preparing) await player.pause()
  } else if (canPlay.value) {
    if (dirty.value && !await saveSettings()) return
    await player.play(selectedId.value)
  }
}
function changeMode(event: Event) { void player.mode((event.target as HTMLSelectElement).value) }

watch(() => player.online, online => { if (online && !songs.value.length && !loadingLibrary.value) void refreshLibrary() })
watch([() => player.state?.selected_song_id, loadingDetail, saving, deleting], ([id]) => {
  if (loadingDetail.value || saving.value || deleting.value) return
  if (!selectedId.value) { chooseInitialSong(); return }
  const selected = songs.value.find(song => song.id === id)
  if (selected && selected.id !== selectedId.value) void pickSong(selected, false)
})
watch([deviceSignature, loadingDetail, saving, deleting], () => {
  if (detail.value && selectedSong.value && !loadingDetail.value && !saving.value && !deleting.value && analyzedDevice.value !== deviceSignature.value) {
    void pickSong(selectedSong.value, false)
  }
})
onMounted(() => { void refreshLibrary() })
onUnmounted(() => { disposed = true; detailRequest++; libraryRequest++ })
</script>

<template>
  <section class="music-panel">
    <div class="section-heading">
      <div><span class="eyebrow">MIDI PLAYER</span><h2>自动演奏</h2></div>
      <el-button size="small" @click="showOverlay">打开悬浮窗</el-button>
    </div>
    <p class="intro">直接导入 MIDI，选择音轨，让九音手碟同时敲出旋律与和弦。</p>

    <div class="drop-zone" :class="{ dragging, importing }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="onDrop">
      <div><strong>{{ importing ? '正在导入曲目…' : '把 MIDI 拖到这里' }}</strong><span>.mid / .midi · 支持一次导入多首</span></div>
      <el-button :loading="importing" :disabled="deleting" @click="fileInput?.click()">导入 MIDI</el-button>
      <input ref="fileInput" class="file-input" type="file" accept=".mid,.midi" multiple aria-label="选择 MIDI 文件" @change="onFiles" />
    </div>
    <ul v-if="importResults.length" class="import-results" aria-live="polite">
      <li v-for="(result, index) in importResults" :key="index" :class="{ failure: !result.ok }"><span>{{ result.name }}</span><span>{{ result.message }}</span></li>
    </ul>
    <div v-if="libraryError" class="notice error" role="alert">{{ libraryError }} <button @click="refreshLibrary">重试</button></div>

    <div class="library-heading"><h3>曲库 <span>{{ songs.length }}</span></h3><div><button @click="openFolder">旧 TXT 文件夹</button><button :disabled="loadingLibrary || deleting" @click="refreshLibrary">{{ loadingLibrary ? '刷新中…' : '刷新' }}</button></div></div>
    <div class="song-list" aria-label="曲库">
      <p v-if="!songs.length" class="empty">{{ loadingLibrary ? '正在加载曲库…' : '导入第一首 MIDI，旧 TXT 曲目也会保留在这里。' }}</p>
      <div v-for="song in songs" :key="song.id" class="song-row" :class="{ selected: selectedId === song.id }">
        <button class="song" :class="{ selected: selectedId === song.id }" :disabled="saving || deleting" :aria-pressed="selectedId === song.id" :aria-label="`选择曲目 ${song.filename}`" @click="pickSong(song)">
          <span class="format">{{ song.format === 'midi' ? 'MID' : 'TXT' }}</span>
          <span class="song-name">{{ musicName(song.name) }}<small v-if="player.active && player.state?.playing_song_id === song.id">正在演奏</small></span>
          <span class="song-meta">{{ musicTime(song.duration_ms) }}<small>{{ song.track_count }} 轨</small></span>
        </button>
        <button class="delete-song" :disabled="saving || importing || deleting || player.pending || !player.online" :aria-label="`删除曲目 ${song.filename}`" @click="requestDelete(song)">删除</button>
      </div>
    </div>
    <div v-if="deleteTarget" class="notice warning delete-confirmation" role="group" aria-label="删除曲目确认">
      <p>从曲库删除「{{ musicName(deleteTarget.name) }}」？</p>
      <p v-if="player.active && player.state?.playing_song_id === deleteTarget.id">这会先停止这首曲目的演奏。</p>
      <p v-if="!deleteTarget.legacy">电脑中用于导入的原文件会保留。</p>
      <div class="delete-actions">
        <button class="confirm-delete" :disabled="deleting" @click="confirmDelete">{{ deleting ? '正在删除…' : '确认删除' }}</button>
        <button :disabled="deleting" @click="deleteTarget = null; deleteError = ''">取消</button>
      </div>
      <div v-if="deleteError" class="notice error" role="alert">{{ deleteError }}</div>
    </div>

    <div class="transport" :inert="deleting">
      <div class="now-playing"><span>{{ player.status }}</span><strong>{{ playingTitle }}</strong><span>{{ musicTime(player.state?.position_ms ?? 0) }} / {{ musicTime(player.state?.duration_ms ?? 0) }}</span></div>
      <progress :value="player.progress" max="100" aria-label="演奏进度" />
      <div v-if="playbackBlockReason" class="notice warning playback-blocked" role="status" aria-live="polite">
        <span>{{ playbackBlockReason }}</span>
        <button v-if="detail && !loadingDetail" @click="settingsSection?.scrollIntoView({ behavior: 'smooth', block: 'start' })">查看演奏设置</button>
      </div>
      <div class="transport-actions">
        <el-button size="small" :disabled="!player.online || player.pending || !songs.length" @click="player.previous">上一曲</el-button>
        <el-button size="small" type="primary" :loading="player.pending" :disabled="!player.online || (!canPlay && !selectedIsPlaying) || player.preparing" @click="togglePlayback">{{ selectedIsPlaying ? (player.paused ? '继续演奏' : '暂停') : '播放选中曲目' }}</el-button>
        <el-button size="small" :disabled="!player.online || (!player.active && !player.pending)" @click="player.stop">停止</el-button>
        <el-button size="small" :disabled="!player.online || player.pending || !songs.length" @click="player.next">下一曲</el-button>
        <select aria-label="播放模式" :value="player.state?.mode ?? 'sequential'" :disabled="!player.online || player.pending" @change="changeMode"><option v-for="mode in MUSIC_MODES" :key="mode" :value="mode">{{ MUSIC_MODE_NAMES[mode] }}</option></select>
      </div>
      <p v-if="player.active && player.state?.playing_song_id !== selectedId" class="hint">正在演奏的曲目不受列表选择影响；点击「播放选中曲目」才会切换。</p>
      <div v-if="player.error || player.connectionError || player.state?.error" class="notice error" role="alert">{{ player.error || player.connectionError || player.state?.error?.message }}</div>
    </div>

    <div v-if="loadingDetail" class="empty" role="status">正在分析曲目…</div>
    <div v-if="detailError" class="notice error" role="alert">{{ detailError }} <button v-if="selectedSong" @click="pickSong(selectedSong)">重试加载</button></div>
    <section v-if="detail && draft" ref="settingsSection" class="song-detail">
      <div class="detail-heading"><h3>{{ musicName(detail.song.name) }}</h3><span>{{ detail.song.format === 'midi' ? '九音手碟适配' : '兼容 TXT 按键谱' }}</span></div>
      <div v-if="detail.song.format === 'midi'" class="notice" :class="{ warning: oldFirmware }">
        {{ oldFirmware ? '当前为单键固件，和弦会自动按顺序敲出，仍可直接播放 MIDI。' : player.state?.device.midi_supported ? `设备支持 MIDI 和弦，最多同时 ${player.state.device.max_keys} 键。` : '播放时自动连接设备；九键设备同时演奏和弦，单键设备自动顺序敲出。' }}
      </div>
      <fieldset :disabled="saving || deleting">
        <template v-if="detail.song.format === 'midi'">
          <div class="track-heading"><h4>演奏音轨 <span>{{ selectedTrackCount }} 条已选</span></h4><button type="button" @click="draft.selected_tracks = null">选择全部非鼓轨</button></div>
          <div class="track-list">
            <label v-for="track in detail.tracks" :key="track.id" class="track" :class="{ muted: track.percussion || !track.note_count }">
              <input type="checkbox" :checked="!track.percussion && !!track.note_count && trackSelected(track.id)" :disabled="track.percussion || !track.note_count" :aria-label="`音轨 ${track.name || `轨道 ${track.id + 1}`}`" @change="toggleTrack(track.id, $event)" />
              <span>{{ track.name || `轨道 ${track.id + 1}` }}<small>{{ track.note_count }} 音符 · {{ track.percussion ? '鼓轨已排除' : track.pitch_min === null ? '无音符' : `音高 ${track.pitch_min}–${track.pitch_max}` }}</small></span>
            </label>
          </div>
        </template>
        <div class="settings-grid">
          <label><span>演奏速度</span><select v-model.number="draft.speed" aria-label="演奏速度"><option :value="0.25">0.25×</option><option :value="0.5">0.5×</option><option :value="0.75">0.75×</option><option :value="1">1× · 原速</option><option :value="1.25">1.25×</option><option :value="1.5">1.5×</option><option :value="2">2×</option></select></label>
          <template v-if="detail.song.format === 'midi'">
            <label><span>移调（半音）</span><input v-model.number="draft.transpose" aria-label="移调（半音）" type="number" min="-36" max="36" step="1" /></label>
            <label><span>音高映射</span><select v-model="draft.range_policy" aria-label="音高映射"><option value="degree">音级折叠 · 与原转谱脚本一致</option><option value="nearest">转调后就近映射</option><option value="smooth">平滑映射</option></select></label>
            <label><span>原曲主调</span><select v-model="draft.root" aria-label="原曲主调"><option :value="null">自动识调 · 与原脚本一致</option><option v-for="(name, index) in ['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B']" :key="index" :value="index">{{ name }}</option></select></label>
          </template>
        </div>
        <label class="silence"><input v-model="draft.skip_leading_silence" type="checkbox" />跳过开头空白</label>
      </fieldset>
      <div class="save-row"><span>{{ dirty ? '有未保存的调整，点击播放会自动保存。' : '设置已保存' }}{{ player.active ? ' · 调整在下次播放时生效' : '' }}</span><el-button size="small" :loading="saving" :disabled="!dirty || !player.online || deleting" @click="saveSettings">保存并重新分析</el-button></div>

      <div class="analysis" :class="{ stale: dirty }">
        <div><strong>{{ detail.analysis.playable_notes }}</strong><span>可演奏音符</span></div><div><strong>{{ detail.analysis.chord_count }}</strong><span>和弦起点</span></div><div><strong>{{ detail.analysis.max_keys }}</strong><span>最多同时按键</span></div>
      </div>
      <p class="analysis-summary">原曲 {{ detail.analysis.source_notes }} 音符 · 全部映射演奏<span v-if="detail.analysis.root_name"> · 原曲主调 {{ detail.analysis.root_name }}</span></p>
      <p v-if="detail.analysis.retrigger_conflicts || detail.analysis.capacity_conflicts" class="hint">密集重击 {{ detail.analysis.retrigger_conflicts }} 处 · 超容量音符 {{ detail.analysis.capacity_conflicts }} 个，已自动顺延演奏</p>
      <ul v-if="detail.analysis.warnings.length" class="warnings"><li v-for="warning in detail.analysis.warnings" :key="warning">{{ warning }}</li></ul>
      <p class="hint">密集重击、同键映射和超容量和弦会自动分次演奏，保留全部音符。</p>
    </section>
  </section>
</template>

<style scoped>
.music-panel { color: #d4dce8; min-width: 0; }
.section-heading, .library-heading, .detail-heading, .track-heading, .save-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { font-size: 21px; font-weight: 600; margin: 4px 0 0; letter-spacing: .3px; }
h3, h4 { margin: 0; font-weight: 500; font-size: 13px; }
.eyebrow { font-size: 9px; letter-spacing: 2.2px; color: #83afd9; }
.intro, .hint, .analysis-summary { font-size: 12px; line-height: 1.7; color: #8c9bb0; margin: 10px 0 14px; }
.drop-zone { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px; border: 1px dashed #3b526f; border-radius: 12px; background: #1a2534; transition: background .15s; }
.drop-zone.dragging { background: #263b55; border-color: #77b5fb; }
.drop-zone strong { display: block; font-size: 13px; font-weight: 500; }.drop-zone span { display: block; font-size: 10px; color: #8a9cb5; margin-top: 5px; }
.file-input { display: none; }.library-heading { margin: 22px 0 10px; }.library-heading h3 span { color: #7c8ba0; font-size: 11px; margin-left: 6px; }
button { font-family: inherit; }button:disabled { cursor: not-allowed; opacity: .5; }
.library-heading button, .track-heading button, .notice button { border: 0; background: none; color: #8cb7ea; cursor: pointer; font-size: 11px; padding: 4px 0 4px 12px; }
.song-list { border: 1px solid #2b3543; border-radius: 10px; max-height: 190px; overflow: auto; background: #141b24; }
.song-row { display: flex; align-items: center; border-bottom: 1px solid #222d3c; }.song-row:last-child { border-bottom: 0; }.song-row.selected { background: #253a54; }
.song { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; padding: 11px 12px; border: 0; background: none; color: #c3cedd; text-align: left; cursor: pointer; }
.song:hover { background: #202d3f; }.format { display: grid; place-items: center; font-size: 9px; letter-spacing: .5px; width: 31px; height: 29px; flex-shrink: 0; border: 1px solid #435b76; border-radius: 7px; color: #9cb8d8; }
.delete-song { flex-shrink: 0; margin: 0 10px 0 0; padding: 6px 5px; border: 0; border-radius: 5px; background: none; color: #df9da5; font-size: 11px; cursor: pointer; }.delete-song:hover { background: #4b2d36; color: #ffc2c9; }
.delete-confirmation { margin-top: 10px; }.delete-confirmation p { margin: 0 0 7px; }.delete-actions { display: flex; gap: 8px; margin-top: 10px; }.delete-actions button { border: 1px solid #655442; border-radius: 5px; padding: 6px 10px; color: #d7c9b6; }.delete-actions button.confirm-delete { background: #b94d5d; border-color: #b94d5d; color: white; }
.song-name { flex: 1; min-width: 0; overflow-wrap: anywhere; font-size: 12px; }.song small { display: block; font-size: 10px; color: #8197b1; margin-top: 3px; }.song-meta { text-align: right; font-size: 11px; color: #a5b5ca; }
.empty { color: #8796aa; font-size: 12px; padding: 20px 16px; line-height: 1.7; margin: 0; }
.transport { margin-top: 16px; padding: 14px; background: #1b2636; border: 1px solid #324258; border-radius: 11px; }.now-playing { display: flex; align-items: center; gap: 9px; font-size: 10px; color: #93a9c5; }.now-playing strong { flex: 1; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: 12px; color: #e0e9f5; font-weight: 500; }
progress { appearance: none; width: 100%; height: 4px; border: 0; border-radius: 5px; overflow: hidden; margin: 12px 0; background: #334257; }progress::-webkit-progress-bar { background: #334257; }progress::-webkit-progress-value { background: #77b1ee; }
.transport-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }.transport-actions :deep(.el-button + .el-button) { margin-left: 0; }.transport-actions select { font-size: 11px; padding: 4px 7px; }
.song-detail { margin-top: 24px; padding-top: 18px; border-top: 1px solid #2b3543; }.detail-heading { margin-bottom: 13px; }.detail-heading h3 { overflow-wrap: anywhere; }.detail-heading > span { flex-shrink: 0; font-size: 10px; color: #7d91ac; }
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }.track-heading { margin: 17px 0 9px; }.track-heading h4 span { margin-left: 5px; font-size: 10px; color: #788da9; }.track-list { max-height: 180px; overflow: auto; border: 1px solid #2b3543; border-radius: 8px; }.track { display: flex; gap: 8px; align-items: flex-start; padding: 9px 10px; border-bottom: 1px solid #24303e; font-size: 12px; cursor: pointer; }.track:last-child { border-bottom: 0; }.track span { min-width: 0; overflow-wrap: anywhere; }.track small { display: block; color: #7f92aa; margin-top: 4px; font-size: 10px; }.track.muted { opacity: .55; cursor: default; }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }.settings-grid label { display: flex; flex-direction: column; gap: 7px; font-size: 11px; color: #9daec3; }
select, input[type=number] { box-sizing: border-box; min-width: 0; max-width: 100%; border: 1px solid #3a4a60; border-radius: 6px; background: #151e2a; color: #dce6f4; padding: 7px 8px; font: inherit; font-size: 12px; }input[type=checkbox] { accent-color: #6da6e7; margin: 2px 0 0; flex-shrink: 0; }.silence { display: flex; align-items: center; gap: 7px; font-size: 11px; color: #a4b4c9; margin-top: 15px; }.save-row { margin: 16px 0; flex-wrap: wrap; }.save-row > span { font-size: 10px; color: #8ba0bb; }
.analysis { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }.analysis > div { border: 1px solid #2d3d52; border-radius: 8px; background: #192535; padding: 12px 8px; }.analysis strong { display: block; font-size: 20px; font-weight: 500; color: #c8ddf6; }.analysis span { display: block; font-size: 10px; margin-top: 5px; color: #8ba1bc; }.analysis.stale { opacity: .5; }.analysis-summary { font-size: 10px; margin-bottom: 8px; }
.notice { border-radius: 7px; padding: 10px 12px; color: #9db8d9; background: #1e2c3e; font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }.notice.warning { background: #332d21; color: #dcc28a; }.notice.error { background: #38282c; color: #f0a8ad; margin-top: 10px; }.warnings { padding-left: 18px; color: #c6ad7e; font-size: 11px; line-height: 1.7; }.import-results { list-style: none; padding: 0; margin: 9px 0; max-height: 140px; overflow: auto; }.import-results li { display: flex; gap: 10px; justify-content: space-between; color: #8ec4ac; padding: 4px 1px; font-size: 11px; }.import-results li span:first-child { min-width: 0; overflow-wrap: anywhere; }.import-results li.failure { color: #e5a4aa; }
.playback-blocked { margin-bottom: 12px; }.playback-blocked button { padding-left: 0; display: block; margin-top: 4px; }
button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid #7eb2ef; outline-offset: 2px; }
@media (max-width: 950px) { .detail-heading { align-items: flex-start; }.detail-heading > span { font-size: 9px; }.drop-zone { padding: 12px; }.drop-zone span { font-size: 9px; }.settings-grid { gap: 10px; } }
</style>
