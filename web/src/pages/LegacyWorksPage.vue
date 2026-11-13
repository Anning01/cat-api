<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { Download, FileJson, RefreshCw, FolderArchive } from 'lucide-vue-next'
import { request } from '@/api'
import type { SingleResponse } from '@/types'
import { exportProject } from '@/features/legacy-works/transfer'
import AppButton from '@/components/AppButton.vue'
import AppPagination from '@/components/AppPagination.vue'
interface Work {id:number;name:string;description:string|null;chapters:number;updated_at:string}
const works=ref<Work[]>([]), total=ref(0), page=ref(1), search=ref(''), loading=ref(false), error=ref('')
const active=ref(new Set<number>()), failures=ref(new Map<number,string>())
const operations=new Map<number,AbortController>()
let epoch=0
function download(blob:Blob,name:string){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
async function load(){const current=++epoch;loading.value=true;error.value='';try{const {data}=await request<SingleResponse<{items:Work[];pagination:{total:number}}>>(`/legacy-works/projects?page=${page.value}&page_size=20&search=${encodeURIComponent(search.value)}`);if(current===epoch){works.value=data.items;total.value=data.pagination.total}}catch(e){if(current===epoch)error.value=e instanceof Error?e.message:'读取作品失败'}finally{if(current===epoch)loading.value=false}}
async function save(work:Work,complete:boolean){
 if(active.value.has(work.id))return
 const operation=new AbortController();operations.set(work.id,operation);active.value=new Set([...active.value,work.id]);failures.value.delete(work.id)
 try{
  if(complete)download(await exportProject(work.id,operation.signal),work.name+'.zip')
  else {const {data}=await request<SingleResponse<Record<string,unknown>>>(`/legacy-works/projects/${work.id}/snapshot`,{signal:operation.signal});download(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),work.name+'-原始资料.json')}
 }catch(e){if(!operation.signal.aborted)failures.value.set(work.id,e instanceof Error?e.message:'下载失败，请重试')}
 finally{active.value=new Set([...active.value].filter(id=>id!==work.id));operations.delete(work.id)}
}
function cancel(id:number){operations.get(id)?.abort()}
onBeforeUnmount(()=>{++epoch;for(const operation of operations.values())operation.abort()})
void load()
</script>
<template><main class="account-page legacy-works"><header class="account-header"><div><span class="eyebrow">YOUR CREATIVE WORK, PRESERVED</span><h1>历史作品迁移</h1><p class="muted">你在线上创作的作品仍保留在这里，可下载并同步到本地猫影继续使用。</p></div><AppButton variant="secondary" :loading="loading" @click="load"><RefreshCw :size="16"/>刷新</AppButton></header>
<section class="account-card legacy-guide"><FolderArchive :size="24"/><div><h2>把作品带回本地</h2><p>下载完整作品包 → 打开本地猫影「我的创作」→「导入作品」。剧本、资产、分镜、画布与可访问的媒体会一并迁移。</p><p class="muted">目前不设自动删除时间。后续关闭迁移通道前会另行通知。原始资料文件只含创作数据与媒体引用，不能替代包含媒体的完整作品包。</p></div></section>
<form class="account-filters" @submit.prevent="page=1;load()"><label>查找作品<input v-model="search" placeholder="输入作品名称"></label><AppButton type="submit" variant="secondary" :disabled="loading">搜索</AppButton><span class="muted">共 {{total}} 个作品</span></form>
<p v-if="error" class="account-error" role="alert">{{error}} <button @click="load">重试</button></p>
<section class="legacy-grid"><article v-for="work in works" :key="work.id" class="account-card legacy-work"><div><span class="muted">#{{work.id}} · {{work.chapters}} 章</span><h2>{{work.name}}</h2><p class="muted">{{work.description||'原始剧本与制作资料已保留。'}}</p></div><p v-if="failures.has(work.id)" class="account-error" role="alert">{{failures.get(work.id)}}。也可先下载原始资料保留文稿。</p><div class="legacy-actions"><AppButton :loading="active.has(work.id)" @click="save(work,true)"><Download :size="15"/>下载完整作品包</AppButton><AppButton variant="secondary" :disabled="active.has(work.id)" @click="save(work,false)"><FileJson :size="15"/>下载原始资料</AppButton><AppButton v-if="active.has(work.id)" variant="ghost" @click="cancel(work.id)">取消下载</AppButton></div></article></section>
<div v-if="!works.length&&!error" class="account-empty">{{loading?'正在读取历史作品…':'当前账户下暂无历史作品'}}</div><AppPagination :page="page" :page-size="20" :page-size-options="[20]" :total="total" @page-change="next=>{page=next;load()}"/></main></template>
<style scoped>.legacy-guide{display:flex;align-items:flex-start;gap:18px;margin-bottom:28px;background:var(--app-accent-soft)}.legacy-guide>svg{color:var(--app-accent);flex-shrink:0}.legacy-guide h2{font-size:16px;margin:0 0 10px}.legacy-guide p{font-size:13px;line-height:1.8;margin:6px 0}.legacy-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,380px),1fr));gap:20px}.legacy-work{display:flex;flex-direction:column;gap:26px;justify-content:space-between}.legacy-work h2{font-size:21px;margin:12px 0}.legacy-work>div>.muted{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.legacy-actions{display:flex;flex-wrap:wrap;gap:10px}.legacy-work .account-error{font-size:13px;line-height:1.7;margin:0}</style>
