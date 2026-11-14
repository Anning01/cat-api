<script setup lang="ts">
import { useId, computed, onBeforeUnmount, ref, watch } from 'vue'
import { Copy, Eye, EyeOff, Plus, RefreshCw } from 'lucide-vue-next'
import ConsolePage from '@/components/ConsolePage.vue'
import UsageMetric from '@/components/UsageMetric.vue'
import UsageDistribution from '@/features/platform/UsageDistribution.vue'
import UsageTrend from '@/features/platform/UsageTrend.vue'
import ConsoleTable from '@/components/ConsoleTable.vue'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import ApiKeyCreateDialog from '@/features/platform/ApiKeyCreateDialog.vue'
import type { ApiKeyRow as KeyRow, CreatedApiKey } from '@/features/platform/apiKeys'
import AppPagination from '@/components/AppPagination.vue'
import ModelCatalog, { type CatalogModel } from '@/features/platform/ModelCatalog.vue'
import PlatformApiDocs from '@/features/platform/PlatformApiDocs.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { API_BASE, request } from '@/api'
import { tr, dateLocale } from '@/i18n'
import { money, dateTime, rechargeOpen } from '@/shared/console'
import { notice } from '@/shared/notice'
import { appConfirm } from '@/shared/confirmDialog'
import type { BillingSummary, SingleResponse } from '@/types'

type Section='usage'|'models'|'docs'|'keys'
const props=defineProps<{section:Section}>(),auth=useAuthStore()
const titles:Record<Section,string>={usage:'用量概览',models:'模型目录',docs:'接口文档',keys:'API Keys'}
const descriptions:Record<Section,string>={usage:'查看模型用量、费用与账户余额。',models:'浏览与调用平台模型，支持图片、视频、文本等多模态能力',docs:'查询接口、请求示例与接入说明。',keys:'管理密钥的模型权限和有效期。'}
const loading=ref(false),error=ref(''),summary=ref<BillingSummary>(),models=ref<CatalogModel[]>([]),keys=ref<KeyRow[]>([]),days=ref(7)
const usageRevision=ref(0)
const modelSearch=ref(''),modelSort=ref('cost-desc'),keySearch=ref(''),keyStatus=ref(''),keyPage=ref(1),keyPageSize=ref(20),selected=ref<number[]>([])
const drawerOpen=ref(false),revoking=ref(false)
const revealedKeys=ref<Record<number,string>>({}),keySecretBusy=ref<Record<number,boolean>>({}),keySecretErrors=ref<Record<number,string>>({})
let epoch=0
const apiBase=computed(()=>new URL(API_BASE,location.href).origin+'/v1')
const modelStats=computed(()=>(summary.value?.by_model??[]).filter(row=>row.model.toLowerCase().includes(modelSearch.value.toLowerCase())).slice().sort((a,b)=>modelSort.value==='name'?a.model.localeCompare(b.model,dateLocale.value):modelSort.value==='records'?(b.record_count??0)-(a.record_count??0):b.cost-a.cost))
function isExpired(key:KeyRow){return key.is_expired===true||Boolean(key.expires_at&&Date.parse(key.expires_at)<=Date.now())}
const filteredKeys=computed(()=>keys.value.filter(key=>(!keyStatus.value||(keyStatus.value==='expired')===isExpired(key))&&(!keySearch.value||(key.name+' '+key.preview).toLowerCase().includes(keySearch.value.toLowerCase()))))
const modelCalls=computed(()=>new Map(models.value.map(model=>[model.id,model.alias||model.id])))
const modelNames=computed(()=>new Map(models.value.map(model=>[model.id,model.name])))
const visibleKeys=computed(()=>filteredKeys.value.slice((keyPage.value-1)*keyPageSize.value,keyPage.value*keyPageSize.value))
const allSelected=computed(()=>visibleKeys.value.length>0&&visibleKeys.value.every(key=>selected.value.includes(key.id)))
watch([keySearch,keyStatus],()=>{keyPage.value=1;selected.value=[]})
async function load(){
 const current=++epoch;loading.value=true;error.value='';revealedKeys.value={};keySecretBusy.value={};keySecretErrors.value={}
 try{
  if(props.section==='usage'){const result=await request<SingleResponse<BillingSummary>>('/platform/usage?days='+days.value);if(current===epoch){summary.value=result.data;usageRevision.value++}}
  else if(props.section==='models'){const result=await request<SingleResponse<CatalogModel[]>>('/platform/catalog');if(current===epoch)models.value=result.data}
  else if(props.section==='keys'){const [result,catalog]=await Promise.all([request<SingleResponse<KeyRow[]>>('/platform/keys'),request<SingleResponse<CatalogModel[]>>('/platform/catalog').catch(()=>null)]);if(current===epoch){keys.value=result.data;models.value=catalog?.data??[];selected.value=selected.value.filter(id=>keys.value.some(key=>key.id===id));keyPage.value=Math.min(keyPage.value,Math.max(1,Math.ceil(keys.value.length/keyPageSize.value)))}}
 }catch(cause){if(current===epoch)error.value=cause instanceof Error?cause.message:tr('加载失败')}
 finally{if(current===epoch)loading.value=false}
}
function changeDays(){days.value=Math.max(1,Math.min(90,Math.trunc(Number(days.value)||7)));void load()}
function created(result:CreatedApiKey){
 const {key,...row}=result;keys.value=[row,...keys.value];revealedKeys.value[row.id]=key
 keySearch.value='';keyStatus.value='';keyPage.value=1
 notice.success(tr('API Key 已创建，可随时查看或复制。'))
}
async function accessKeySecret(key:KeyRow,action:'view'|'copy'){
 if(!key.can_reveal||keySecretBusy.value[key.id])return
 delete keySecretErrors.value[key.id]
 if(action==='view'&&revealedKeys.value[key.id]){delete revealedKeys.value[key.id];return}
 const current=epoch;keySecretBusy.value[key.id]=true
 try{
  let value=revealedKeys.value[key.id]
  if(!value)value=(await request<SingleResponse<{key:string}>>('/platform/keys/'+key.id+'/secret',{cache:'no-store'})).data.key
  if(current!==epoch||!keys.value.some(row=>row.id===key.id))return
  if(action==='view'){revealedKeys.value[key.id]=value;return}
  try{await navigator.clipboard.writeText(value)}catch{revealedKeys.value[key.id]=value;throw new Error(tr('复制失败，密钥已显示，可手动复制。'))}
  notice.success(tr('已复制'))
 }catch(cause){if(current===epoch)keySecretErrors.value[key.id]=cause instanceof Error?cause.message:tr('读取密钥失败，请重试')}
 finally{if(current===epoch)keySecretBusy.value[key.id]=false}
}
function toggleSelection(id:number){selected.value=selected.value.includes(id)?selected.value.filter(value=>value!==id):[...selected.value,id]}
function toggleAll(){selected.value=allSelected.value?selected.value.filter(id=>!visibleKeys.value.some(key=>key.id===id)):[...new Set([...selected.value,...visibleKeys.value.map(key=>key.id)])]}
async function revoke(ids:number[]){
 if(revoking.value||!ids.length)return
 const current=epoch
 if(!await appConfirm({title:tr('停用 API Key'),message:tr('将停用 {p0} 个密钥，使用这些密钥的应用将无法继续调用。',{p0:ids.length}),confirmLabel:tr('停用')})||current!==epoch)return
 revoking.value=true
 try{for(const id of ids){await request('/platform/keys/'+id,{method:'DELETE'});if(current!==epoch)return;keys.value=keys.value.filter(key=>key.id!==id);selected.value=selected.value.filter(value=>value!==id);delete revealedKeys.value[id];delete keySecretErrors.value[id]}notice.success(tr('密钥已停用'))}
 catch(cause){notice.error(cause instanceof Error?cause.message:tr('操作失败'))}
 finally{if(current===epoch){revoking.value=false;keyPage.value=Math.min(keyPage.value,Math.max(1,Math.ceil(filteredKeys.value.length/keyPageSize.value)))}}
}
watch(()=>props.section,()=>{++epoch;summary.value=undefined;models.value=[];keys.value=[];selected.value=[];revealedKeys.value={};keySecretBusy.value={};keySecretErrors.value={};drawerOpen.value=false;revoking.value=false;void load()},{immediate:true})
onBeforeUnmount(()=>{++epoch;revealedKeys.value={};keySecretErrors.value={}})
const formId=useId()
</script>
<template>
 <ConsolePage :title="tr(titles[section])" :description="tr(descriptions[section])" :class="'platform-'+section">
  <template #actions><template v-if="section==='usage'"><div class="console-inline"><label :for="formId+'-field-1'" class="console-inline">{{ tr('近') }}<input name="field-1" :id="formId+'-field-1'" v-model.number="days" class="days-input" type="number" min="1" max="90" :aria-label="tr('统计天数')" @change="changeDays"/>{{ tr('天') }}</label><AppButton v-for="value in [7,30]" :key="value" variant="secondary" :active="days===value" @click="days=value;load()">{{ tr('近 {p0} 天',{p0:value}) }}</AppButton></div></template><AppButton v-if="section!=='docs'" variant="secondary" :loading="loading" @click="load"><RefreshCw :size="16"/>{{ tr('刷新') }}</AppButton><AppButton v-if="section==='keys'" variant="primary" @click="drawerOpen=true"><Plus :size="16"/>{{ tr('创建 API Key') }}</AppButton></template>
  <p v-if="error" class="console-error" role="alert">{{ error }} <button @click="load">{{ tr('重试') }}</button></p>
  <div v-if="loading&&!summary&&!models.length&&!keys.length&&section!=='docs'" class="console-skeleton" role="status">{{ tr('正在加载…') }}<i v-for="n in 6" :key="n"/></div>
  <template v-else-if="section==='usage'&&summary">
   <div class="usage-metrics">
     <UsageMetric :label="tr('账户余额')" :value="'¥ '+money(auth.balance)"><AppButton size="xs" @click="rechargeOpen=true">{{ tr('充值') }} →</AppButton></UsageMetric>
     <UsageMetric :label="tr('所选期间费用')" :value="'¥ '+money(summary.total_cost)"/>
     <UsageMetric :label="tr('计费记录')" :value="summary.total_records.toLocaleString(dateLocale)"/>
     <UsageMetric v-if="summary.pending_records" :label="tr('待结算 / 待核对')" :value="String(summary.pending_records)"/>
   </div>
   <div class="usage-grid"><UsageTrend :days="summary.daily_trend" :revision="usageRevision"/><UsageDistribution :items="summary.by_billing_type" :revision="usageRevision"/></div>
   <section class="console-table-panel"><div class="console-table-toolbar"><h2>{{ tr('按模型统计') }}</h2><div class="console-inline"><input v-model="modelSearch" :placeholder="tr('搜索模型名称')" :aria-label="tr('搜索模型名称')"/><AppSelect v-model="modelSort" :ariaLabel="tr('模型统计排序')" :options="[{value:'cost-desc',label:tr('按费用从高到低')},{value:'records',label:tr('按计费记录排序')},{value:'name',label:tr('按名称排序')}]"/></div></div><ConsoleTable :caption="tr('按模型统计')"><thead><tr><th scope="col">{{ tr('模型名称') }}</th><th scope="col" class="numeric">{{ tr('计费记录') }}</th><th scope="col" class="numeric">{{ tr('总费用') }}</th><th scope="col" class="numeric">{{ tr('占比') }}</th></tr></thead><tbody><tr v-for="row in modelStats" :key="row.model"><th scope="row">{{ row.model }}</th><td class="numeric">{{ row.record_count??'—' }}</td><td class="numeric">¥ {{ money(row.cost) }}</td><td class="numeric">{{ summary.total_cost>0?(row.cost/summary.total_cost*100).toFixed(1)+'%':'—' }}</td></tr></tbody></ConsoleTable><p v-if="!modelStats.length" class="console-empty">{{ tr('所选期间暂无计费记录') }}</p></section>
  </template>
  <ModelCatalog v-else-if="section==='models'&&!error" :models="models" :can-manage="auth.isSuperAdmin" :logged-in="auth.isLoggedIn"/>
  <PlatformApiDocs v-else-if="section==='docs'" :base-url="apiBase" :can-manage="auth.isSuperAdmin"/>
  <template v-else-if="section==='keys'">
   <section class="console-table-panel key-table-panel" :aria-busy="loading">
    <div class="console-table-toolbar"><h2>API Keys <small>{{ filteredKeys.length }}</small></h2>
     <search><form class="key-toolbar-filters" @submit.prevent>
      <label class="visually-hidden" :for="formId+'-field-2'">{{ tr('搜索') }}</label><input :id="formId+'-field-2'" v-model="keySearch" type="search" name="key_search" :placeholder="tr('密钥名称或前缀')"/>
      <AppSelect v-model="keyStatus" :ariaLabel="tr('密钥状态')" :options="[{value:'',label:tr('全部状态')},{value:'active',label:tr('有效')},{value:'expired',label:tr('已过期')}]"/>
      <AppButton variant="secondary" :disabled="!selected.length||revoking" :loading="revoking" @click="revoke([...selected])">{{ tr('停用所选') }} ({{ selected.length }})</AppButton>
     </form></search>
    </div>
    <ConsoleTable v-if="filteredKeys.length" caption="API Keys"><thead><tr><th scope="col"><input type="checkbox" :checked="allSelected" :aria-label="tr('选择当前页')" @change="toggleAll"/></th><th scope="col">{{ tr('名称') }}</th><th scope="col">API Key</th><th scope="col">{{ tr('可用模型') }}</th><th scope="col">{{ tr('有效期') }}</th><th scope="col">{{ tr('创建时间') }}</th><th scope="col" class="row-actions">{{ tr('操作') }}</th></tr></thead>
     <tbody><tr v-for="key in visibleKeys" :key="key.id"><td><input type="checkbox" :checked="selected.includes(key.id)" :aria-label="tr('选择 {p0}',{p0:key.name})" @change="toggleSelection(key.id)"/></td><th scope="row">{{ key.name }}</th><td class="key-secret-cell"><code class="key-token">{{ revealedKeys[key.id]||key.preview }}</code>
       <div v-if="key.can_reveal" class="key-secret-actions"><AppButton size="xs" :loading="keySecretBusy[key.id]" :aria-label="tr(revealedKeys[key.id]?'隐藏密钥 {p0}':'查看密钥 {p0}',{p0:key.name})" :aria-pressed="Boolean(revealedKeys[key.id])" @click="accessKeySecret(key,'view')"><component :is="revealedKeys[key.id]?EyeOff:Eye" :size="13" aria-hidden="true"/>{{ tr(revealedKeys[key.id]?'隐藏':'查看') }}</AppButton><AppButton size="xs" :disabled="keySecretBusy[key.id]" :aria-label="tr('复制密钥 {p0}',{p0:key.name})" @click="accessKeySecret(key,'copy')"><Copy :size="13" aria-hidden="true"/>{{ tr('复制') }}</AppButton></div>
       <small v-else class="muted">{{ tr('旧密钥尚无可恢复副本') }}</small>
       <small v-if="keySecretErrors[key.id]" role="alert" class="text-danger">{{ keySecretErrors[key.id] }}</small>
      </td>
      <td><span v-if="key.allowed_model_ids==null">{{ tr('全部模型') }}</span><details v-else class="key-model-scope"><summary>{{ tr('指定 {p0} 个模型',{p0:key.allowed_model_ids.length}) }}</summary><ul><li v-for="modelId in key.allowed_model_ids" :key="modelId">{{ modelNames.get(modelId)||modelId }}<code v-if="modelCalls.has(modelId)">{{ modelCalls.get(modelId) }}</code></li></ul></details></td>
      <td class="date-cell"><strong v-if="isExpired(key)" class="text-danger">{{ tr('已过期') }}</strong><span v-else-if="!key.expires_at">{{ tr('永不过期') }}</span><span v-if="key.expires_at">{{ dateTime(key.expires_at) }}</span></td>
      <td class="date-cell">{{ dateTime(key.created_at) }}</td><td class="row-actions"><AppButton variant="danger" size="sm" :disabled="revoking" @click="revoke([key.id])">{{ tr('停用') }}</AppButton></td>
     </tr></tbody>
    </ConsoleTable>
    <div v-if="!filteredKeys.length&&!error" class="console-empty key-empty"><h3>{{ tr(keys.length?'没有找到匹配的密钥':'还没有 API Key') }}</h3><p>{{ tr(keys.length?'可以调整筛选条件后重试。':'创建密钥，设置可用模型和有效期后即可接入。') }}</p><AppButton v-if="keys.length" variant="secondary" @click="keySearch='';keyStatus=''">{{ tr('清空筛选') }}</AppButton></div>
    <AppPagination :page="keyPage" :page-size="keyPageSize" :total="filteredKeys.length" @page-change="value=>keyPage=value" @size-change="value=>{keyPageSize=value;keyPage=1}"/>
   </section>
  </template>
  <ApiKeyCreateDialog v-model="drawerOpen" @created="created"/>

 </ConsolePage>
</template>

<style scoped>
.key-secret-cell { min-width:180px; max-width:300px; }
.key-token { display:block; max-width:280px; overflow-wrap:anywhere; white-space:normal; font:12px/1.5 ui-monospace,monospace; user-select:all; }
.key-secret-actions { display:flex; align-items:center; gap:4px; margin-top:3px; }
.key-secret-cell > small { max-width:280px; font-size:11px; }
</style>
