<script setup lang="ts">
import { computed } from 'vue'
import { money } from '@/shared/console'
import { tr } from '@/i18n'

const props = defineProps<{ amount: number; multiplier: number; unit: string }>()
const discounted = computed(() => props.multiplier < 1 && props.amount > 0)
</script>

<template>
  <span class="unit-price">
    <strong :class="{ discounted }"><span v-if="discounted" class="visually-hidden">{{ tr('折后价') }}</span>¥{{ money(amount * multiplier) }}</strong>
    <del v-if="discounted"><span class="visually-hidden">{{ tr('原价') }}</span>¥{{ money(amount) }}</del>
    <small>/ {{ unit }}</small>
  </span>
</template>

<style scoped>
.unit-price { display: inline-flex; align-items: baseline; justify-content: flex-end; flex-wrap: wrap; gap: 2px 6px; font-variant-numeric: tabular-nums; }
strong { font-size: 14px; font-weight: 650; color: var(--app-text); }
.discounted { color: var(--app-accent); }
del, small { color: var(--app-text-secondary); font-size: 11px; }
</style>
