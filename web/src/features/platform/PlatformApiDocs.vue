<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { BookOpen, Copy, Download, ExternalLink, RefreshCw, Settings2 } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import AppDialog from '@/components/AppDialog.vue'
import { request } from '@/api'
import { tr } from '@/i18n'
import { notice } from '@/shared/notice'
import type { SingleResponse } from '@/types'

const props=defineProps<{baseUrl:string;canManage?:boolean}>()
const url=ref(''),loading=ref(true),error=ref(''),editOpen=ref(false),draft=ref(''),saving=ref(false),saveError=ref('')
const frameRevision=ref(0),frameLoading=ref(false),slow=ref(false)
const formId=useId(),dialog=ref<InstanceType<typeof AppDialog>>()
const importUrl=computed(()=>props.baseUrl.replace(/\/$/,'')+'/openapi.json')
const exportUrl=computed(()=>props.baseUrl.replace(/\/v1\/?$/,'')+'/api/platform/openapi-export')
const externalUrl=computed(()=>{
 try{const value=new URL(url.value);return value.protocol==='https:'&&!value.username&&!value.password&&value.origin!==location.origin?value.href:''}
 catch{return ''}
})
let epoch=0,timer:ReturnType<typeof setTimeout>|undefined
async function load(){
 const current=++epoch;loading.value=true;error.value=''
 try{const result=await request<SingleResponse<{url:string}>>('/platform/documentation');if(current===epoch)url.value=result.data.url}
 catch(cause){if(current===epoch)error.value=cause instanceof Error?cause.message:tr('加载失败')}
 finally{if(current===epoch)loading.value=false}
}
function configure(){draft.value=url.value;saveError.value='';editOpen.value=true}
async function save(){
 if(saving.value)return
 saving.value=true;saveError.value=''
 try{
  await request('/platform/documentation',{method:'PATCH',body:JSON.stringify({url:draft.value.trim()})})
  notice.success(tr('文档地址已保存'))
  // A fresh HTML response applies the CSP allowlist for the newly configured document origin.
  location.reload()
 }catch(cause){saveError.value=cause instanceof Error?cause.message:tr('保存失败')}
 finally{saving.value=false}
}
async function copyImportUrl(){
 try{await navigator.clipboard.writeText(importUrl.value);notice.success(tr('OpenAPI 地址已复制'))}
 catch{notice.error(tr('复制失败，请手动复制'))}
}
function loaded(){frameLoading.value=false;slow.value=false;if(timer)clearTimeout(timer)}
watch([externalUrl,frameRevision],()=>{
 if(timer)clearTimeout(timer)
 frameLoading.value=Boolean(externalUrl.value);slow.value=false
 if(externalUrl.value)timer=setTimeout(()=>{slow.value=true},12000)
})
onMounted(load)
onBeforeUnmount(()=>{++epoch;if(timer)clearTimeout(timer)})
</script>

<template>
 <div class="docs-workspace">
  <div class="docs-toolbar">
   <div class="docs-toolbar-source"><BookOpen :size="17" aria-hidden="true"/><span>Apifox</span><span class="docs-status">{{ tr(externalUrl?'在线文档':'待发布') }}</span></div>
   <div class="docs-toolbar-actions">
    <a class="docs-link" :href="exportUrl" download="cat-api-openapi.json"><Download :size="15" aria-hidden="true"/>{{ tr('下载 OpenAPI') }}</a>
    <a v-if="externalUrl" class="docs-link" :href="externalUrl" target="_blank" rel="noopener noreferrer"><ExternalLink :size="15" aria-hidden="true"/>{{ tr('新窗口打开') }}</a>
    <AppButton v-if="externalUrl" size="sm" variant="secondary" :aria-label="tr('重新加载文档')" @click="frameRevision++"><RefreshCw :size="15"/></AppButton>
    <AppButton v-if="canManage" size="sm" variant="secondary" @click="configure"><Settings2 :size="15" aria-hidden="true"/>{{ tr('文档设置') }}</AppButton>
   </div>
  </div>
  <div v-if="error" class="console-error" role="alert">{{ error }} <AppButton size="sm" @click="load">{{ tr('重试') }}</AppButton></div>
  <div v-else-if="loading" class="docs-placeholder" role="status">{{ tr('正在加载…') }}</div>
  <template v-else-if="externalUrl">
   <p v-if="slow" class="docs-load-note">{{ tr('文档加载较慢，可在新窗口打开查看。') }}</p>
   <div class="docs-frame-shell" :aria-busy="frameLoading">
    <span v-if="frameLoading&&!slow" class="docs-frame-loading">{{ tr('正在加载…') }}</span>
    <iframe :key="frameRevision" :src="externalUrl" :title="tr('Cat API 在线接口文档')" referrerpolicy="no-referrer" sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads" allow="clipboard-write" @load="loaded" @error="slow=true;frameLoading=false"/>
   </div>
  </template>
  <div v-else class="docs-placeholder">
   <BookOpen :size="32" class="docs-placeholder-icon" aria-hidden="true"/>
   <h2>{{ tr(url?'请使用独立的文档域名':'在线文档待发布') }}</h2>
   <p>{{ tr(canManage?'将 OpenAPI 导入 Apifox，发布文档站后填写公开链接，即可在这里完整展示。':'在线接口文档正在准备中，当前可下载 OpenAPI 查看接口定义。') }}</p>
   <div v-if="canManage" class="docs-import-source"><label :for="formId+'-import'">{{ tr('Apifox 导入地址') }}</label><div><input :id="formId+'-import'" :value="importUrl" readonly/><AppButton variant="secondary" :aria-label="tr('复制 OpenAPI 地址')" @click="copyImportUrl"><Copy :size="16"/></AppButton></div></div>
   <AppButton v-if="canManage" variant="primary" @click="configure">{{ tr('配置在线文档') }}</AppButton>
  </div>
  <AppDialog ref="dialog" v-model="editOpen" :title="tr('文档设置')" width="560px" guard-changes :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving">
   <form class="docs-settings-form" @submit.prevent="save">
    <label :for="formId+'-url'">{{ tr('Apifox 公开文档链接') }}</label>
    <input :id="formId+'-url'" v-model="draft" type="url" inputmode="url" autocomplete="off" autofocus placeholder="https://your-project.apifox.cn/" :aria-describedby="formId+'-hint'"/>
    <p :id="formId+'-hint'">{{ tr('使用公开 HTTPS 链接或独立文档域名，不填写访问密码或密钥。留空可暂停展示，保存后刷新生效。') }}</p>
    <p v-if="saveError" class="console-error" role="alert">{{ saveError }}</p>
    <div class="docs-settings-export"><a :href="exportUrl" download="cat-api-openapi.json">{{ tr('下载 OpenAPI JSON，重新导入 Apifox') }}</a><AppButton size="sm" variant="ghost" @click="copyImportUrl">{{ tr('复制导入地址') }}</AppButton></div>
    <footer><AppButton variant="secondary" :disabled="saving" @click="dialog?.requestClose()">{{ tr('取消') }}</AppButton><AppButton type="submit" variant="primary" :loading="saving">{{ tr('保存并应用') }}</AppButton></footer>
   </form>
  </AppDialog>
 </div>
</template>

<style scoped>
.docs-workspace { display:flex; flex:1; min-height:0; min-width:0; flex-direction:column; }
.docs-toolbar { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px 16px; padding:0 0 12px; }
.docs-toolbar-source,.docs-toolbar-actions { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.docs-toolbar-source { color:var(--app-text); font-size:13px; font-weight:600; }
.docs-toolbar-source > svg { color:var(--app-accent); }
.docs-status { color:var(--app-text-secondary); font-size:11px; font-weight:400; }
.docs-link { display:inline-flex; align-items:center; gap:6px; min-height:32px; font-size:12px; text-decoration:none; }
.docs-link:focus-visible { outline:2px solid var(--app-accent); outline-offset:3px; }
.docs-frame-shell { position:relative; display:flex; flex:1; min-height:280px; border:1px solid var(--app-border); border-radius:8px; overflow:clip; background:var(--app-surface); }
iframe { flex:1; display:block; width:100%; min-height:100%; border:0; color-scheme:normal; }
.docs-frame-loading { position:absolute; z-index:1; top:12px; left:50%; transform:translateX(-50%); padding:6px 12px; border-radius:6px; background:var(--app-surface-muted); color:var(--app-text-secondary); font-size:12px; pointer-events:none; }
.docs-load-note { margin:0 0 8px; color:var(--app-text-secondary); font-size:12px; }
.docs-placeholder { display:flex; flex:1; min-height:320px; align-items:center; justify-content:center; flex-direction:column; gap:16px; padding:32px 16px; border:1px solid var(--app-border); border-radius:8px; background:var(--app-surface); text-align:center; }
.docs-placeholder-icon { color:var(--app-accent); }
.docs-placeholder h2 { margin:0; font-size:18px; }
.docs-placeholder > p { max-width:54ch; margin:0; color:var(--app-text-secondary); font-size:13px; }
.docs-import-source { width:min(100%,520px); display:grid; gap:8px; margin-bottom:4px; text-align:left; }
.docs-import-source label { font-size:12px; color:var(--app-text-secondary); }
.docs-import-source > div { display:flex; gap:8px; }
.docs-import-source input { flex:1; min-width:0; font-size:12px; }
.docs-settings-form { display:grid; gap:10px; }
.docs-settings-form > label { font-size:13px; color:var(--app-text); }
.docs-settings-form input { min-height:40px; width:100%; padding:8px 10px; border:1px solid var(--app-border-strong); border-radius:6px; background:var(--app-surface); color:var(--app-text); font:inherit; font-size:13px; }
.docs-settings-form input:focus-visible { outline:2px solid var(--app-accent); outline-offset:2px; }
.docs-settings-form > p { margin:0; color:var(--app-text-secondary); font-size:12px; line-height:1.6; }
.docs-settings-export { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; padding-block:16px; margin-top:8px; border-top:1px solid var(--app-border); font-size:12px; }
.docs-settings-form footer { display:flex; justify-content:flex-end; gap:8px; }
@media(max-width:767px) { .docs-toolbar-actions { gap:8px; } .docs-link { min-height:44px; } .docs-frame-shell { min-height:65dvh; } .docs-settings-form input { font-size:16px; min-height:44px; } }
</style>
