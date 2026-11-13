<script setup lang="ts">
import { ElDropdown, ElDropdownMenu, ElDropdownItem } from 'element-plus'
import { MoreHorizontal } from 'lucide-vue-next'
import AppButton from './AppButton.vue'
import { tr } from '@/i18n'
defineProps<{ items: Array<{ value: string; label: string; danger?: boolean; disabled?: boolean }> }>()
const emit = defineEmits<{ select: [value: string] }>()
</script>
<template>
  <ElDropdown trigger="click" @command="value=>emit('select',String(value))">
    <AppButton icon-only size="sm" :aria-label="tr('更多操作')"><MoreHorizontal :size="17"/></AppButton>
    <template #dropdown><ElDropdownMenu><ElDropdownItem v-for="item in items" :key="item.value" :command="item.value" :disabled="item.disabled" :class="{'text-danger':item.danger}">{{ tr(item.label) }}</ElDropdownItem></ElDropdownMenu></template>
  </ElDropdown>
</template>
