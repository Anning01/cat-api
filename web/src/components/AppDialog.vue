<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useAttrs, useId, watch } from 'vue'
import { X } from 'lucide-vue-next'
import AppButton from './AppButton.vue'
import { appConfirm } from '@/shared/confirmDialog'
import { tr } from '@/i18n'

defineOptions({ inheritAttrs: false })
const props=withDefaults(defineProps<{title:string;width?:string;size?:string;drawer?:boolean;side?:'left'|'right';closeOnClickModal?:boolean;closeOnPressEscape?:boolean;showClose?:boolean;guardChanges?:boolean}>(),{width:'480px',side:'right',closeOnClickModal:true,closeOnPressEscape:true,showClose:true,guardChanges:false})
const open=defineModel<boolean>({required:true})
const emit=defineEmits<{closed:[]}>()
const attrs=useAttrs(),id=useId(),dialog=ref<HTMLDialogElement>(),dirty=ref(false)
let pressedOutside=false,confirming=false
watch(open,async value=>{
  await nextTick()
  if(value!==open.value)return
  if(value){dirty.value=false;if(!dialog.value?.open)dialog.value?.showModal()}
  else if(dialog.value?.open)dialog.value.close()
},{immediate:true,flush:'post'})
async function requestClose(){
  if(!props.showClose||confirming)return
  if(props.guardChanges&&dirty.value){
    confirming=true
    const discard=await appConfirm({title:tr('放弃未保存的修改？'),message:tr('关闭后将丢弃尚未提交的内容。'),confirmLabel:tr('放弃修改'),cancelLabel:tr('继续编辑'),tone:'warning'})
    confirming=false
    if(!discard)return
  }
  open.value=false
}
function cancel(event:Event){event.preventDefault();if(props.closeOnPressEscape)void requestClose()}
function outside(event:PointerEvent){const rect=dialog.value!.getBoundingClientRect();return event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom}
function pointerDown(event:PointerEvent){pressedOutside=outside(event)}
function pointerUp(event:PointerEvent){if(pressedOutside&&outside(event)&&props.closeOnClickModal)void requestClose();pressedOutside=false}
function closed(){open.value=false;if(dialog.value)dialog.value.returnValue='';emit('closed')}
onBeforeUnmount(()=>{if(dialog.value?.open)dialog.value.close()})
defineExpose({ requestClose })
</script>
<template>
  <Teleport to="body">
    <dialog ref="dialog" :id="attrs.id as string | undefined" :class="['app-dialog',attrs.class,{'is-drawer':drawer,'is-left':side==='left'}]" :style="{width:drawer?(size||'640px'):width}" :aria-labelledby="id+'-title'" :aria-describedby="!showClose?id+'-busy':undefined" @cancel="cancel" @close="closed" @pointerdown="pointerDown" @pointerup="pointerUp">
      <template v-if="open"><header class="app-dialog-header"><h2 :id="id+'-title'">{{ title }}</h2><AppButton v-if="showClose" icon-only :aria-label="tr('关闭')" @click="requestClose"><X :size="20"/></AppButton></header><div class="app-dialog-body" @input="dirty=true"><p v-if="!showClose" :id="id+'-busy'" class="muted" role="status">{{ tr('正在处理，请稍候…') }}</p><slot/></div><footer v-if="$slots.footer" class="app-dialog-footer"><slot name="footer"/></footer></template>
    </dialog>
  </Teleport>
</template>
<style scoped>
.app-dialog{max-width:calc(100vw - 32px);max-height:calc(100dvh - 32px);margin:auto;padding:0;border:1px solid var(--app-border);border-radius:8px;color:var(--app-text);background:var(--app-surface);box-shadow:var(--app-shadow);overscroll-behavior:contain}
.app-dialog[open]{display:flex;flex-direction:column}.app-dialog::backdrop{background:rgb(0 0 0 / 42%);overflow:hidden;overscroll-behavior:contain}
.app-dialog-header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-shrink:0;padding:16px 24px;border-bottom:1px solid var(--app-border)}.app-dialog-header h2{margin:0;font-size:18px;font-weight:600;line-height:1.5}
.app-dialog-body{padding:24px;overflow:auto;overscroll-behavior:contain;min-height:0}.app-dialog-footer{display:flex;justify-content:flex-end;gap:8px;padding:16px 24px;border-top:1px solid var(--app-border);flex-shrink:0}
.app-dialog.is-drawer{position:fixed;inset:0 0 0 auto;margin:0;max-width:100vw;max-height:100dvh;height:100dvh;border-radius:0;border:0;border-left:1px solid var(--app-border)}.app-dialog.is-drawer .app-dialog-body{flex:1}.app-dialog.is-left{inset:0 auto 0 0;border:0;border-right:1px solid var(--app-border)}
@media(max-width:767px){.app-dialog-body{padding:20px 16px}.app-dialog-header,.app-dialog-footer{padding:14px 16px}}
</style>
