<script setup lang="ts">
withDefaults(defineProps<{ tone?: 'success' | 'warning' | 'danger' | 'neutral' }>(), { tone: 'neutral' })
</script>
<template><span class="status-badge" :class="'status-badge--' + tone"><slot /></span></template>
