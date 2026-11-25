<script setup lang="ts">
import type { PetDetails } from '../api/client'
import { petPercent } from '../composables/usePetViewer'

defineProps<{ pet: PetDetails; compact?: boolean }>()
</script>

<template>
  <article class="pet-details" :class="{ compact, shiny: pet.shiny }">
    <div class="pet-heading">
      <div class="pet-avatar" aria-hidden="true">{{ pet.shiny ? '✦' : '◈' }}</div>
      <div class="pet-title"><h3>{{ pet.name }}</h3><span :title="pet.bloodline_tip">{{ pet.bloodline_label || '血脉未知' }}</span></div>
      <span v-if="pet.shiny" class="shiny-badge">{{ pet.shiny_hint || '异色' }}</span>
    </div>
    <div class="nature-card" :title="pet.nature_tip">
      <span class="metric-label">原始性格</span>
      <div class="nature-content"><strong data-testid="pet-nature">{{ pet.nature || '未知' }}</strong><span>{{ pet.nature_hint || '等待属性下发' }}</span></div>
    </div>
    <div class="pet-metrics">
      <div :title="pet.voice_tip"><span class="metric-label">声音</span><strong>{{ petPercent(pet.voice) }}</strong><small>{{ pet.voice_hint || (pet.voice == null ? '未下发' : '无声音奖牌') }}</small></div>
      <div :title="pet.height_tip"><span class="metric-label">身高</span><strong>{{ petPercent(pet.height) }}</strong><small>{{ pet.height_hint || (pet.height == null ? '未下发' : '范围内比例') }}</small></div>
      <div :title="pet.weight_tip"><span class="metric-label">体重</span><strong>{{ petPercent(pet.weight) }}</strong><small>{{ pet.weight_hint || (pet.weight == null ? '未下发' : '无体型奖牌') }}</small></div>
    </div>
    <details v-if="!compact" class="pet-evidence">
      <summary>查看属性详情</summary>
      <p>{{ pet.nature_tip }}</p>
      <p>{{ pet.height_tip }}</p><p>{{ pet.weight_tip }}</p>
      <p>{{ pet.bloodline_tip }}</p>
      <p>佩戴奖章：{{ pet.medal || '未下发' }} · {{ pet.shiny_hint || '异色未知' }}</p>
    </details>
  </article>
</template>

<style scoped>
.pet-details { border: 1px solid #334155; border-radius: 14px; padding: 20px; background: #19212d; color: #d8e3ef; }
.pet-details.shiny { border-color: #89713f; }.pet-heading { display: flex; gap: 12px; align-items: center; margin-bottom: 18px; }.pet-avatar { display: grid; place-items: center; width: 43px; height: 43px; border-radius: 13px; background: #263e44; color: #91d5c6; font-size: 28px; }.shiny .pet-avatar { color: #e8cd87; background: #433b2a; }.pet-title { flex: 1; min-width: 0; }.pet-title h3 { font-size: 20px; line-height: 1.3; margin: 0 0 4px; overflow-wrap: anywhere; }.pet-title span { color: #9bacbf; font-size: 12px; }.shiny-badge { padding: 4px 7px; font-size: 10px; color: #e8cd87; background: #433b2a; border-radius: 6px; white-space: nowrap; }
.nature-card { background: #22342f; border: 1px solid #35564a; border-radius: 10px; padding: 13px 16px; }.metric-label { display: block; font-size: 11px; color: #99a9bc; margin-bottom: 6px; }.nature-card .metric-label { color: #a7c5b7; }.nature-content { display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; }.nature-content strong { font-size: 26px; font-weight: 600; color: #b6e7cd; }.nature-content span { font-size: 13px; color: #b4c9bd; }.pet-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; padding-top: 16px; }.pet-metrics > div { min-width: 0; }.pet-metrics strong { display: block; font-size: 20px; font-variant-numeric: tabular-nums; font-weight: 500; }.pet-metrics small { display: block; margin-top: 5px; font-size: 11px; color: #96a8bd; }.pet-evidence { margin-top: 18px; padding-top: 12px; border-top: 1px solid #2d3949; font-size: 12px; color: #9aaec5; }.pet-evidence summary { cursor: pointer; }.pet-evidence p { white-space: pre-line; line-height: 1.7; }
.compact { padding: 12px; border-radius: 10px; }.compact .pet-heading { margin-bottom: 10px; gap: 8px; }.compact .pet-avatar { width: 32px; height: 32px; font-size: 23px; border-radius: 9px; }.compact .pet-title h3 { font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.compact .pet-title span { font-size: 10px; }.compact .nature-card { padding: 8px 11px; }.compact .metric-label { margin-bottom: 3px; font-size: 10px; }.compact .nature-content { gap: 12px; }.compact .nature-content strong { font-size: 22px; }.compact .nature-content span { font-size: 11px; }.compact .pet-metrics { padding-top: 10px; }.compact .pet-metrics strong { font-size: 17px; }.compact .pet-metrics small { font-size: 10px; margin-top: 3px; }
</style>
