<script setup lang="ts">
import { computed } from 'vue'
import type { BillingSummary } from '@/types'
import { money, label, billingLabels } from '@/shared/console'
import { tr } from '@/i18n'

const props = defineProps<{ items: BillingSummary['by_billing_type']; revision?: number }>()
const colors = ['var(--app-primary)', '#3e9986', '#c88b4c', '#8998bc', '#a879b1']
const segments = computed(() => {
  const total = props.items.reduce((sum, item) => sum + Math.max(0, item.cost), 0)
  let offset = 0
  return props.items.map((item, i) => {
    const share = total ? Math.max(0, item.cost) / total * 100 : 0
    const segment = { ...item, share, offset, color: colors[i % colors.length] }
    offset += share
    return segment
  })
})
</script>

<template>
  <section class="console-section">
    <div class="section-heading"><h2>{{ tr('费用分布') }}</h2></div>
    <div v-if="segments.length" class="distribution">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r="40" fill="none" stroke="var(--app-surface-muted)" stroke-width="12"/>
        <g :key="revision" transform="rotate(-90 50 50)">
          <circle v-for="item in segments" :key="item.billing_type" class="distribution-segment" cx="50" cy="50" r="40" pathLength="100" fill="none"
            :stroke="item.color" stroke-width="12" :stroke-dasharray="item.share+' '+(100-item.share)" :stroke-dashoffset="-item.offset"/>
        </g>
      </svg>
      <dl><div v-for="item in segments" :key="item.billing_type">
        <dt><i :style="{ background: item.color }"/>{{ label(item.billing_type,billingLabels) }}</dt><dd>¥ {{ money(item.cost) }}</dd>
      </div></dl>
    </div>
    <p v-else class="console-empty">{{ tr('所选期间暂无计费记录') }}</p>
  </section>
</template>

<style scoped>
.distribution { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 12px 18px; padding-block: 12px; }
svg { width: 110px; max-width: 48%; }
dl { min-width: min(100%,140px); flex: 1; margin: 0; }
dl div, dt { display: flex; align-items: center; gap: 6px; }
dl div { justify-content: space-between; padding-block: 6px; font-size: 12px; }
i { width: 7px; height: 7px; border-radius: 50%; }
dd { margin: 0; font-variant-numeric: tabular-nums; }
@media (prefers-reduced-motion: no-preference) {
  .distribution-segment { animation: ring-in 650ms cubic-bezier(.16,1,.3,1); transition: stroke-dasharray .32s, stroke-dashoffset .32s; }
}
@keyframes ring-in { from { stroke-dasharray: 0 100; } }
</style>
