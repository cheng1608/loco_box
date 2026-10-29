<script setup lang="ts">
defineProps<{ error?: Error }>()
const reload = () => window.location.reload()
</script>

<template>
  <div class="view-loading" role="status" aria-live="polite">
    <strong>{{ error ? '界面加载失败' : '正在打开工作台…' }}</strong>
    <template v-if="error">
      <p>请重新加载界面。如果问题持续，请检查启动日志。</p>
      <button @click="reload">重新加载</button>
    </template>
  </div>
</template>

<style scoped>
.view-loading { display: grid; place-content: center; min-height: 100%; text-align: center; padding: 12px; box-sizing: border-box; color: #c2cad6; }
.view-loading p { font-size: 13px; color: #8f9bad; }
.view-loading button { justify-self: center; border: 1px solid #3d5c83; border-radius: 8px; padding: 8px 16px; background: #24374f; color: white; cursor: pointer; }
</style>
