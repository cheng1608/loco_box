<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElScrollbar } from 'element-plus/es/components/scrollbar/index'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/scrollbar/style/css'
import { usePolling } from '../composables/usePolling'
import {
  getMusicState,
  listScores,
  openScoresFolder,
  selectSong,
} from '../api/client'

const scores = ref<string[]>([])
const current = ref('')
const mode = ref('sequential')

const MODE_NAMES: Record<string, string> = {
  sequential: '列表播放',
  single: '单曲播放',
  repeat_one: '单曲循环',
  repeat_all: '列表循环',
  shuffle: '随机播放',
}

function displayName(name: string) {
  return name.replace(/\.txt$/i, '')
}

async function refreshScores() {
  try {
    const { scores: list } = await listScores()
    scores.value = list
  } catch {
    /* 后端未就绪，忽略 */
  }
}

async function refreshState() {
  try {
    const st = await getMusicState()
    current.value = st.current
    mode.value = st.mode
    scores.value = st.playlist
  } catch {
    /* ignore */
  }
}

async function onPick(name: string) {
  try {
    await selectSong(name)
    current.value = name
    ElMessage.success(`已选择 ${displayName(name)}`)
  } catch (e) {
    ElMessage.error(String(e))
  }
}

async function onStart() {
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('show_music_overlay')
  } catch {
    /* 非 Tauri 环境忽略 */
  }
}

async function onOpenFolder() {
  try {
    await openScoresFolder()
  } catch (e) {
    ElMessage.error(String(e))
  }
  refreshScores()
}

onMounted(() => {
  refreshScores()
})
usePolling(refreshState, 1000)
</script>

<template>
  <div class="panel">
    <h2>自动演奏</h2>
    <div class="mode-line">播放模式：{{ MODE_NAMES[mode] || mode }}</div>

    <el-scrollbar class="playlist">
      <div v-if="!scores.length" class="empty">data/scores/ 暂无曲目</div>
      <div
        v-for="s in scores"
        :key="s"
        class="item"
        :class="{ active: s === current }"
        @click="onPick(s)"
      >
        <span class="name">{{ displayName(s) }}</span>
        <span v-if="s === current" class="mark">▶</span>
      </div>
    </el-scrollbar>

    <div class="actions">
      <el-button type="primary" size="large" @click="onStart">启动</el-button>
      <el-button @click="onOpenFolder">打开文件夹</el-button>
      <el-button @click="refreshScores">刷新</el-button>
    </div>
  </div>
</template>

<style scoped>
.panel {
  padding: 8px 4px;
}
.panel h2 {
  font-size: 16px;
  margin: 0 0 6px;
}
.mode-line {
  color: #d8b96a;
  font-size: 13px;
  margin-bottom: 10px;
}
.playlist {
  height: 260px;
  margin-bottom: 10px;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
}
.empty {
  padding: 16px;
  color: #777;
  font-size: 13px;
  text-align: center;
}
.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 12px;
  color: #ccc;
  font-size: 13px;
  cursor: pointer;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.item:hover {
  background: rgba(255, 255, 255, 0.05);
}
.item.active {
  color: #fff;
  background: rgba(64, 158, 255, 0.16);
}
.name {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.mark {
  color: #d8b96a;
  flex-shrink: 0;
}
.actions {
  display: flex;
  gap: 8px;
}
</style>
