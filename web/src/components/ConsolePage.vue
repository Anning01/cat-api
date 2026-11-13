<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <main class="console-page">
    <header class="console-page-header">
      <div class="console-page-heading"><h1 id="console-page-title" tabindex="-1">{{ title }}</h1><slot name="description"><p v-if="description">{{ description }}</p></slot></div>
      <div v-if="$slots.actions" class="console-page-actions"><slot name="actions" /></div>
    </header>
    <slot />
  </main>
</template>
