<script setup lang="ts">
defineProps<{ label: string; value: string }>()
</script>
<template>
  <div class="usage-metric">
    <div class="metric-heading"><span>{{ label }}</span><slot/></div>
    <strong>{{ value }}</strong>
  </div>
</template>
<style scoped>
.usage-metric { min-width: 0; padding: 16px 20px; border-radius: 16px; background: var(--app-surface); border: 1px solid var(--app-border); }
.metric-heading { display: flex; align-items: center; justify-content: space-between; min-height: 28px; color: var(--app-text-secondary); font-size: 13px; }
strong { display: block; margin-top: 6px; font-size: clamp(20px,2vw,26px); font-weight: 650; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
</style>
