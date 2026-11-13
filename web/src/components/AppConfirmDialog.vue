<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { CircleHelp, TriangleAlert, Trash2 } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { appConfirmState, resolveAppConfirm } from '@/shared/confirmDialog'
withDefaults(defineProps<{dark?:boolean}>(),{dark:false})
const dialog=ref<HTMLDialogElement>()
const icon=computed(()=>({danger:Trash2,warning:TriangleAlert,neutral:CircleHelp}[appConfirmState.tone]))
watch(()=>appConfirmState.open,async open=>{await nextTick();if(open&&!dialog.value?.open)dialog.value?.showModal();else if(!open&&dialog.value?.open)dialog.value.close()})
onBeforeUnmount(()=>{if(dialog.value?.open)dialog.value.close();resolveAppConfirm(false)})
</script>
<template><Teleport to="body"><dialog ref="dialog" class="app-confirm-dialog" :class="'is-'+appConfirmState.tone" aria-labelledby="app-confirm-title" :aria-describedby="appConfirmState.message?'app-confirm-message':undefined" @cancel.prevent="resolveAppConfirm(false)" @close="resolveAppConfirm(false);dialog&&(dialog.returnValue='')"><template v-if="appConfirmState.open"><span class="app-confirm-icon"><component :is="icon" :size="21"/></span><div class="app-confirm-copy"><h2 id="app-confirm-title">{{ appConfirmState.title }}</h2><p v-if="appConfirmState.message" id="app-confirm-message">{{ appConfirmState.message }}</p></div><footer class="app-confirm-actions"><AppButton autofocus variant="secondary" @click="resolveAppConfirm(false)">{{ appConfirmState.cancelLabel }}</AppButton><AppButton :variant="appConfirmState.tone==='danger'?'danger':'primary'" @click="resolveAppConfirm(true)">{{ appConfirmState.confirmLabel }}</AppButton></footer></template></dialog></Teleport></template>
<style scoped>
.app-confirm-dialog{width:min(440px,calc(100vw - 32px));max-height:calc(100dvh - 32px);overflow:auto;margin:auto;padding:24px;border:1px solid var(--app-border);border-radius:8px;color:var(--app-text);background:var(--app-surface);box-shadow:var(--app-shadow);overscroll-behavior:contain}.app-confirm-dialog[open]{display:grid;grid-template-columns:36px minmax(0,1fr);gap:16px}.app-confirm-dialog::backdrop{background:rgb(0 0 0 / 45%);overflow:hidden;overscroll-behavior:contain}
.app-confirm-icon{display:grid;width:36px;height:36px;place-items:center;border-radius:6px;color:var(--app-accent);background:var(--app-accent-soft)}.is-danger .app-confirm-icon{color:var(--creation-danger);background:var(--app-danger-soft)}.is-warning .app-confirm-icon{color:var(--creation-warning);background:var(--app-warning-soft)}.app-confirm-copy{min-width:0}.app-confirm-copy h2{margin:0;font-size:17px;line-height:1.5}.app-confirm-copy p{margin:8px 0 0;color:var(--app-text-secondary);font-size:14px;line-height:1.65;overflow-wrap:anywhere}.app-confirm-actions{display:flex;grid-column:1/-1;justify-content:flex-end;gap:8px;margin-top:8px}
</style>
