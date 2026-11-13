<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BillingSummary } from '@/types'
import { money } from '@/shared/console'
import { tr } from '@/i18n'

const props = defineProps<{ days: BillingSummary['daily_trend']; revision?: number }>()
const metric = ref<'cost' | 'records'>('cost')
const activeDate = ref('')
const bars = computed(() => {
  const values = props.days.map(day => day[metric.value] ?? 0)
  const max = Math.max(...values, .000001)
  return props.days.map((day, i) => ({
    date: day.date, ratio: Math.max(0, values[i] ?? 0) / max,
    label: day.date + ' · ' + (metric.value === 'cost' ? '¥ ' + money(day.cost) : String(day.records ?? '—')),
    tick: i % Math.max(1, Math.ceil(props.days.length / 8)) === 0 ? day.date.slice(5) : '',
  }))
})
const selected = computed(() => bars.value.find(bar => bar.date === activeDate.value))
</script>

<template>
  <section class="console-section">
    <div class="section-heading">
      <h2>{{ tr('每日消费趋势') }}</h2>
      <div class="console-segmented">
        <button v-for="key in (['cost','records'] as const)" :key="key" :aria-pressed="metric === key"
          :class="{ 'is-active': metric === key }" @click="metric = key">{{ tr(key === 'cost' ? '消费金额' : '计费记录') }}</button>
      </div>
    </div>
    <div class="chart-readout">{{ selected?.label || tr(metric === 'cost' ? '消费金额' : '计费记录') }}</div>
    <div class="usage-chart-scroll">
      <div :key="revision" class="trend-plot" :style="{ minWidth: bars.length * 24 + 'px' }" role="group" :aria-label="tr('每日消费趋势')">
        <button v-for="bar in bars" :key="bar.date" :aria-label="bar.label" :aria-pressed="activeDate === bar.date"
          @focus="activeDate = bar.date" @pointerenter="activeDate = bar.date" @click="activeDate = bar.date">
          <span class="track"><i :style="{ transform: 'scaleY(' + bar.ratio + ')' }"/></span>
          <small>{{ bar.tick }}</small>
        </button>
      </div>
    </div>
    <p class="muted">{{ tr('按北京时间统计，计费记录不等同于请求成功次数。') }}</p>
    <table class="visually-hidden">
        <caption>{{ tr('每日消费趋势') }}</caption>
        <thead><tr><th scope="col">{{ tr('日期') }}</th><th class="numeric">{{ tr('消费金额') }}</th><th class="numeric">{{ tr('计费记录') }}</th></tr></thead>
        <tbody><tr v-for="day in days" :key="day.date"><th scope="row">{{ day.date }}</th><td class="numeric">¥ {{ money(day.cost) }}</td><td class="numeric">{{ day.records ?? '—' }}</td></tr></tbody>
    </table>
  </section>
</template>

<style scoped>
.chart-readout { font-size: 12px; font-variant-numeric: tabular-nums; color: var(--app-text-secondary); }
.trend-plot { height: 172px; display: flex; gap: 2px; padding: 4px; }
.trend-plot button { display: grid; grid-template-rows: 1fr 20px; gap: 4px; flex: 1; min-width: 0; padding: 0; background: transparent; border: 0; cursor: pointer; color: var(--app-text-secondary); }
.track { display: flex; justify-content: center; border-bottom: 1px solid var(--app-border); }
.track i { width: min(24px, 64%); background: var(--app-primary); border-radius: 8px 8px 2px 2px; transform-origin: bottom; }
button[aria-pressed=true] .track { background: var(--app-accent-soft); border-radius: 8px 8px 0 0; }
button:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 1px; }
small { font-size: 10px; }
@media (prefers-reduced-motion: no-preference) {
  .track i { transition: transform 340ms cubic-bezier(.16,1,.3,1); animation: chart-in 600ms cubic-bezier(.16,1,.3,1); }
}
@keyframes chart-in { from { transform: scaleY(0); } }
</style>
