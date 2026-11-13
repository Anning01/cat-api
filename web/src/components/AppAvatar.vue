<script setup lang="ts">
import { ref, watch } from 'vue'
const props = withDefaults(defineProps<{ name?: string; src?: string; size?: number }>(), { size: 32 })
const failed = ref(false)
watch(() => props.src, () => { failed.value = false })
</script>
<template>
  <span class="app-avatar" :style="{ width: size + 'px', height: size + 'px', fontSize: size * .4 + 'px' }">
    <img v-if="src && !failed" :src="src" :alt="name || ''" @error="failed = true" />
    <span v-else aria-hidden="true">{{ Array.from(name || '?')[0]?.toUpperCase() }}</span>
  </span>
</template>
