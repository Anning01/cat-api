<script setup lang="ts">
defineProps<{ caption: string }>()
</script>
<template>
  <div class="console-table-scroll" tabindex="0" role="region" :aria-label="caption"><table class="console-data-table"><caption class="visually-hidden">{{ caption }}</caption><slot/></table></div>
</template>
