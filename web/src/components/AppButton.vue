<script setup lang="ts">
import { LoaderCircle } from 'lucide-vue-next'

export type AppButtonVariant = 'primary' | 'secondary' | 'soft' | 'ghost' | 'danger' | 'dark'
export type AppButtonSize = 'xs' | 'sm' | 'md' | 'lg'

withDefaults(defineProps<{
  type?: 'button' | 'submit' | 'reset'
  variant?: AppButtonVariant
  size?: AppButtonSize
  disabled?: boolean
  loading?: boolean
  iconOnly?: boolean
  block?: boolean
  active?: boolean
}>(), {
  type: 'button',
  variant: 'ghost',
  size: 'md',
  disabled: false,
  loading: false,
  iconOnly: false,
  block: false,
  active: false,
})
</script>

<template>
  <button
    :type="type"
    class="app-button"
    :class="[
      `app-button--${variant}`,
      `app-button--${size}`,
      { 'is-icon-only': iconOnly, 'is-block': block, 'is-active': active, 'is-loading': loading },
    ]"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
  >
    <LoaderCircle v-if="loading" class="app-button__spinner" aria-hidden="true" />
    <slot />
  </button>
</template>

<style scoped>
.app-button { display:inline-flex; min-width:0; min-height:36px; align-items:center; justify-content:center; gap:7px; margin:0; padding:0 12px; border:1px solid transparent; border-radius:6px; color:var(--app-accent); background:transparent; font:inherit; font-size:14px; font-weight:500; line-height:1.2; white-space:nowrap; appearance:none; cursor:pointer; user-select:none; transition:background-color .15s,color .15s,border-color .15s; }
.app-button--primary { color:var(--app-on-primary); background:var(--app-primary); border-color:var(--app-primary); }
.app-button--primary:hover:not(:disabled) { filter:brightness(.94); }
.app-button--secondary { color:var(--app-text); background:var(--app-surface); border-color:var(--app-border-strong); }
.app-button--secondary:hover:not(:disabled) { background:var(--app-surface-hover); }
.app-button--soft { color:var(--app-accent); background:var(--app-accent-soft); }
.app-button--soft:hover:not(:disabled), .app-button--ghost:hover:not(:disabled), .app-button.is-active { background:var(--app-accent-soft); color:var(--app-accent); }
.app-button--danger { color:var(--creation-danger); background:var(--app-danger-soft); }
.app-button--danger:hover:not(:disabled) { border-color:var(--creation-danger); }
.app-button--dark { color:var(--app-on-primary); background:var(--app-primary); }
.app-button--xs { min-height:28px; padding:0 8px; font-size:12px; }
.app-button--sm { min-height:32px; padding:0 9px; font-size:13px; }
.app-button--lg { min-height:40px; padding:0 16px; }
.app-button.is-icon-only { width:36px; padding:0; flex:0 0 auto; }
.app-button--sm.is-icon-only { width:32px; }
.app-button--lg.is-icon-only { width:40px; }
.app-button.is-block { width:100%; }
.app-button:focus-visible { outline:2px solid var(--app-accent); outline-offset:3px; }
.app-button:disabled { opacity:.5; cursor:not-allowed; }
.app-button__spinner { width:1em; height:1em; animation:app-button-spin .8s linear infinite; }
@keyframes app-button-spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion:reduce) { .app-button { transition:none; } .app-button__spinner { animation:none; } }
@media(max-width:767px) { .app-button { min-height:40px; } }
</style>
