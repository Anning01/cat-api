<script setup lang="ts">
import { useId, computed, onBeforeUnmount, ref, watch } from 'vue'
import AppDialog from '@/components/AppDialog.vue'
import { Copy, Plus, RefreshCw } from 'lucide-vue-next'
import ConsolePage from '@/components/ConsolePage.vue'
import ConsoleTable from '@/components/ConsoleTable.vue'
import AppButton from '@/components/AppButton.vue'
import AppPagination from '@/components/AppPagination.vue'
import ModelCatalog, { type CatalogModel } from '@/features/platform/ModelCatalog.vue'
import PlatformApiDocs from '@/features/platform/PlatformApiDocs.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { API_BASE, request } from '@/api'
import { tr, dateLocale } from '@/i18n'
import { money, dateTime, rechargeOpen, billingLabels, label } from '@/shared/console'
import { notice } from '@/shared/notice'
import { appConfirm } from '@/shared/confirmDialog'
import type { BillingSummary, SingleResponse } from '@/types'

type Section='usage'|'models'|'docs'|'keys'
interface KeyRow {id:number;name:string;preview:string;created_at:string;purpose?:'api'|'studio'}
const props=defineProps<{section:Section}>(),auth=useAuthStore()
const titles:Record<Section,string>={usage:'用量概览',models:'模型目录',docs:'接口文档',keys:'API Keys'}
const descriptions:Record<Section,string>={usage:'查看模型用量、费用与账户余额。',models:'浏览与调用平台模型，支持图片、视频、文本等多模态能力',docs:'查询接口、请求示例与接入说明。',keys:'管理账户的 API 密钥，用于调用平台模型'}
const loading=ref(false),error=ref(''),summary=ref<BillingSummary>(),models=ref<CatalogModel[]>([]),keys=ref<KeyRow[]>([]),days=ref(7)
const chartMetric=ref<'cost'|'records'>('cost'),modelSearch=ref(''),modelSort=ref('cost-desc'),keySearch=ref(''),keyPurpose=ref(''),keyPage=ref(1),keyPageSize=ref(20),selected=ref<number[]>([])
const drawerOpen=ref(false),name=ref(''),purpose=ref<'api'|'studio'>('api'),secret=ref(''),creating=ref(false),createError=ref(''),revoking=ref(false)
let epoch=0
const apiBase=computed(()=>new URL(API_BASE,location.href).origin+'/v1')
const range=computed(()=>summary.value?.daily_trend??[])
const chartMax=computed(()=>Math.max(.000001,...range.value.map(day=>chartMetric.value==='cost'?day.cost:day.records??0)))
const modelStats=computed(()=>(summary.value?.by_model??[]).filter(row=>row.model.toLowerCase().includes(modelSearch.value.toLowerCase())).slice().sort((a,b)=>modelSort.value==='name'?a.model.localeCompare(b.model,dateLocale.value):modelSort.value==='records'?(b.record_count??0)-(a.record_count??0):b.cost-a.cost))
const filteredKeys=computed(()=>keys.value.filter(key=>(!keyPurpose.value||(key.purpose??'api')===keyPurpose.value)&&(!keySearch.value||(key.name+' '+key.preview).toLowerCase().includes(keySearch.value.toLowerCase()))))
const visibleKeys=computed(()=>filteredKeys.value.slice((keyPage.value-1)*keyPageSize.value,keyPage.value*keyPageSize.value))
const allSelected=computed(()=>visibleKeys.value.length>0&&visibleKeys.value.every(key=>selected.value.includes(key.id)))
watch([keySearch,keyPurpose],()=>{keyPage.value=1;selected.value=[]})
const shares=computed(()=>summary.value?.by_billing_type??[])
async function load(){
 const current=++epoch;loading.value=true;error.value=''
 try{
  if(props.section==='usage'){const result=await request<SingleResponse<BillingSummary>>('/platform/usage?days='+days.value);if(current===epoch)summary.value=result.data}
  else if(props.section==='models'){const result=await request<SingleResponse<CatalogModel[]>>('/platform/catalog');if(current===epoch)models.value=result.data}
  else if(props.section==='keys'){const result=await request<SingleResponse<KeyRow[]>>('/platform/keys');if(current===epoch){keys.value=result.data;selected.value=selected.value.filter(id=>keys.value.some(key=>key.id===id));keyPage.value=Math.min(keyPage.value,Math.max(1,Math.ceil(keys.value.length/keyPageSize.value)))}}
 }catch(cause){if(current===epoch)error.value=cause instanceof Error?cause.message:tr('加载失败')}
 finally{if(current===epoch)loading.value=false}
}
function changeDays(){days.value=Math.max(1,Math.min(90,Math.trunc(Number(days.value)||7)));void load()}
async function copy(value:string){try{await navigator.clipboard.writeText(value);notice.success(tr('已复制'))}catch{notice.error(tr('复制失败，请手动复制'))}}
async function create(){
 if(creating.value)return
 if(!name.value.trim()){createError.value=tr('请输入密钥名称');return}
 const current=epoch;creating.value=true;createError.value=''
 try{const result=await request<SingleResponse<KeyRow&{key:string}>>('/platform/keys',{method:'POST',body:JSON.stringify({name:name.value.trim(),purpose:purpose.value})});if(current===epoch){secret.value=result.data.key;keys.value=[{...result.data,purpose:purpose.value},...keys.value];drawerOpen.value=false;name.value='';keyPage.value=1}}
 catch(cause){if(current===epoch)createError.value=cause instanceof Error?cause.message:tr('创建失败')}
 finally{if(current===epoch)creating.value=false}
}
function toggleSelection(id:number){selected.value=selected.value.includes(id)?selected.value.filter(value=>value!==id):[...selected.value,id]}
function toggleAll(){selected.value=allSelected.value?selected.value.filter(id=>!visibleKeys.value.some(key=>key.id===id)):[...new Set([...selected.value,...visibleKeys.value.map(key=>key.id)])]}
async function revoke(ids:number[]){
 if(revoking.value||!ids.length)return
 const current=epoch
 if(!await appConfirm({title:tr('停用 API Key'),message:tr('将停用 {p0} 个密钥，使用这些密钥的应用将无法继续调用。',{p0:ids.length}),confirmLabel:tr('停用')})||current!==epoch)return
 revoking.value=true
 try{for(const id of ids){await request('/platform/keys/'+id,{method:'DELETE'});if(current!==epoch)return;keys.value=keys.value.filter(key=>key.id!==id);selected.value=selected.value.filter(value=>value!==id)}notice.success(tr('密钥已停用'))}
 catch(cause){notice.error(cause instanceof Error?cause.message:tr('操作失败'))}
 finally{if(current===epoch){revoking.value=false;keyPage.value=Math.min(keyPage.value,Math.max(1,Math.ceil(filteredKeys.value.length/keyPageSize.value)))}}
}
watch(()=>props.section,()=>{++epoch;summary.value=undefined;models.value=[];keys.value=[];selected.value=[];secret.value='';drawerOpen.value=false;creating.value=false;revoking.value=false;void load()},{immediate:true})
onBeforeUnmount(()=>{++epoch;secret.value=''})
const keyDialog=ref<InstanceType<typeof AppDialog>>()
const formId=useId()
</script>
<template>
 <ConsolePage :title="tr(titles[section])" :description="tr(descriptions[section])" :class="'platform-'+section">
  <template #actions><template v-if="section==='usage'"><div class="console-inline"><label :for="formId+'-field-1'" class="console-inline">{{ tr('近') }}<input name="field-1" :id="formId+'-field-1'" v-model.number="days" class="days-input" type="number" min="1" max="90" :aria-label="tr('统计天数')" @change="changeDays"/>{{ tr('天') }}</label><AppButton v-for="value in [7,30]" :key="value" variant="secondary" :active="days===value" @click="days=value;load()">{{ tr('近 {p0} 天',{p0:value}) }}</AppButton></div></template><AppButton v-if="section!=='docs'" variant="secondary" :loading="loading" @click="load"><RefreshCw :size="16"/>{{ tr('刷新') }}</AppButton><AppButton v-if="section==='keys'" variant="primary" @click="createError='';drawerOpen=true"><Plus :size="16"/>{{ tr('创建 API Key') }}</AppButton></template>
  <p v-if="error" class="console-error" role="alert">{{ error }} <button @click="load">{{ tr('重试') }}</button></p>
  <div v-if="loading&&!summary&&!models.length&&!keys.length&&section!=='docs'" class="console-skeleton" role="status">{{ tr('正在加载…') }}<i v-for="n in 6" :key="n"/></div>
  <template v-else-if="section==='usage'&&summary">
   <div class="console-summary"><div><span>{{ tr('账户余额') }}</span><strong>¥ {{ money(auth.balance) }}</strong><AppButton @click="rechargeOpen=true">{{ tr('充值') }} →</AppButton></div><div><span>{{ tr('所选期间费用') }}</span><strong>¥ {{ money(summary.total_cost) }}</strong></div><div><span>{{ tr('计费记录') }}</span><strong>{{ summary.total_records.toLocaleString(dateLocale) }}</strong></div><div v-if="summary.pending_records"><span>{{ tr('待结算 / 待核对') }}</span><strong>{{ summary.pending_records }}</strong></div></div>
   <div class="usage-grid"><section class="console-section"><div class="section-heading"><h2>{{ tr('每日消费趋势') }}</h2><div class="console-segmented"><button :aria-pressed="chartMetric==='cost'" :class="{'is-active':chartMetric==='cost'}" @click="chartMetric='cost'">{{ tr('消费金额') }}</button><button :aria-pressed="chartMetric==='records'" :class="{'is-active':chartMetric==='records'}" @click="chartMetric='records'">{{ tr('计费记录') }}</button></div></div><div class="usage-chart-scroll"><div class="usage-chart" :style="{minWidth:Math.max(280,range.length*22)+'px'}" role="group" :aria-label="tr(chartMetric==='cost'?'每日消费':'每日计费记录')"><div v-for="(day,index) in range" :key="day.date" class="usage-bar-column"><div class="usage-bar-track"><button class="usage-bar" :style="{height:((chartMetric==='cost'?day.cost:day.records??0)/chartMax*100)+'%'}" :aria-label="day.date+' · '+(chartMetric==='cost'?'¥ '+money(day.cost):String(day.records??0))" :title="day.date+' · '+(chartMetric==='cost'?'¥ '+money(day.cost):String(day.records??0))"/></div><small>{{ index%Math.max(1,Math.ceil(range.length/8))===0?day.date.slice(5):'' }}</small></div></div></div><p class="muted">{{ tr('按北京时间统计，计费记录不等同于请求成功次数。') }}</p><details class="chart-data"><summary>{{ tr('图表数据') }}</summary><ConsoleTable :caption="tr('每日消费趋势')"><thead><tr><th scope="col">{{ tr('日期') }}</th><th scope="col" class="numeric">{{ tr('消费金额') }}</th><th scope="col" class="numeric">{{ tr('计费记录') }}</th></tr></thead><tbody><tr v-for="day in range" :key="day.date"><th scope="row">{{ day.date }}</th><td class="numeric">¥ {{ money(day.cost) }}</td><td class="numeric">{{ day.records??'—' }}</td></tr></tbody></ConsoleTable></details></section><section class="console-section"><div class="section-heading"><h2>{{ tr('费用分布') }}</h2></div><div v-for="item in shares" :key="item.billing_type" class="usage-share"><div><span>{{ label(item.billing_type,billingLabels) }}</span><strong>¥ {{ money(item.cost) }}</strong></div><meter :value="Math.max(0,item.cost)" :max="Math.max(.000001,summary.total_cost)" :aria-label="label(item.billing_type,billingLabels)"/></div><p v-if="!shares.length" class="console-empty">{{ tr('所选期间暂无计费记录') }}</p></section></div>
   <section class="console-table-panel"><div class="console-table-toolbar"><h2>{{ tr('按模型统计') }}</h2><div class="console-inline"><input v-model="modelSearch" :placeholder="tr('搜索模型名称')" :aria-label="tr('搜索模型名称')"/><select v-model="modelSort" :aria-label="tr('模型统计排序')"><option value="cost-desc">{{ tr('按费用从高到低') }}</option><option value="records">{{ tr('按计费记录排序') }}</option><option value="name">{{ tr('按名称排序') }}</option></select></div></div><ConsoleTable :caption="tr('按模型统计')"><thead><tr><th scope="col">{{ tr('模型名称') }}</th><th scope="col" class="numeric">{{ tr('计费记录') }}</th><th scope="col" class="numeric">{{ tr('总费用') }}</th><th scope="col" class="numeric">{{ tr('占比') }}</th></tr></thead><tbody><tr v-for="row in modelStats" :key="row.model"><th scope="row">{{ row.model }}</th><td class="numeric">{{ row.record_count??'—' }}</td><td class="numeric">¥ {{ money(row.cost) }}</td><td class="numeric">{{ summary.total_cost>0?(row.cost/summary.total_cost*100).toFixed(1)+'%':'—' }}</td></tr></tbody></ConsoleTable><p v-if="!modelStats.length" class="console-empty">{{ tr('所选期间暂无计费记录') }}</p></section>
  </template>
  <ModelCatalog v-else-if="section==='models'&&!error" :models="models" :can-manage="auth.isSuperAdmin" :logged-in="auth.isLoggedIn"/>
  <PlatformApiDocs v-else-if="section==='docs'" :base-url="apiBase"/>
  <template v-else-if="section==='keys'">
   <form class="console-filterbar" @submit.prevent><label :for="formId+'-field-2'">{{ tr('搜索') }}<input name="field-2" :id="formId+'-field-2'" v-model="keySearch" :placeholder="tr('密钥名称或前缀')"/></label><label :for="formId+'-field-3'">{{ tr('用途') }}<select name="field-3" :id="formId+'-field-3'" v-model="keyPurpose"><option value="">{{ tr('全部') }}</option><option value="api">{{ tr('通用 API') }}</option><option value="studio">{{ tr('猫影工作台') }}</option></select></label><AppButton variant="secondary" :disabled="!selected.length||revoking" :loading="revoking" @click="revoke([...selected])">{{ tr('停用所选') }} ({{ selected.length }})</AppButton></form>
   <section class="console-table-panel" :aria-busy="loading"><div class="console-table-toolbar"><h2>{{ tr('有效 API Keys') }} <small>{{ filteredKeys.length }}</small></h2><span class="muted">{{ tr('密钥归当前账户所有。') }}</span></div><ConsoleTable :caption="tr('有效 API Keys')"><thead><tr><th scope="col"><input type="checkbox" :checked="allSelected" :aria-label="tr('选择当前页')" @change="toggleAll"/></th><th scope="col">{{ tr('名称') }}</th><th scope="col">{{ tr('密钥前缀') }}</th><th scope="col">{{ tr('用途') }}</th><th scope="col">{{ tr('创建时间') }}</th><th scope="col" class="row-actions">{{ tr('操作') }}</th></tr></thead><tbody><tr v-for="key in visibleKeys" :key="key.id"><td><input type="checkbox" :checked="selected.includes(key.id)" :aria-label="tr('选择 {p0}',{p0:key.name})" @change="toggleSelection(key.id)"/></td><th scope="row">{{ key.name }}</th><td><code>{{ key.preview }}</code></td><td>{{ tr(key.purpose==='studio'?'猫影工作台':'通用 API') }}</td><td>{{ dateTime(key.created_at) }}</td><td class="row-actions"><AppButton variant="danger" size="sm" :disabled="revoking" @click="revoke([key.id])">{{ tr('停用') }}</AppButton></td></tr></tbody></ConsoleTable><div v-if="!filteredKeys.length&&!error" class="console-empty"><h3>{{ tr(keys.length?'没有找到匹配的密钥':'还没有 API Key') }}</h3><p>{{ tr('创建密钥后，在应用中使用 Base URL 和 API Key 调用模型。') }}</p><AppButton v-if="!keys.length" variant="primary" @click="drawerOpen=true">{{ tr('创建 API Key') }}</AppButton><AppButton v-else variant="secondary" @click="keySearch='';keyPurpose=''">{{ tr('清空筛选') }}</AppButton></div><AppPagination :page="keyPage" :page-size="keyPageSize" :total="filteredKeys.length" @page-change="value=>keyPage=value" @size-change="value=>{keyPageSize=value;keyPage=1}"/></section>
  </template>
  <AppDialog ref="keyDialog" drawer guard-changes v-model="drawerOpen" class="console-drawer" :title="tr('创建 API Key')" size="min(480px, 100vw)" :close-on-click-modal="!creating" :close-on-press-escape="!creating" :show-close="!creating"><form class="console-form" @submit.prevent="create"><label :for="formId+'-field-4'">{{ tr('密钥名称') }}<input name="field-4" :id="formId+'-field-4'" v-model="name" autofocus maxlength="80" required autocomplete="off" :placeholder="tr('例如：我的应用')"/></label><label :for="formId+'-field-5'">{{ tr('用途') }}<select name="field-5" :id="formId+'-field-5'" v-model="purpose"><option value="api">{{ tr('通用 API') }}</option><option value="studio">{{ tr('猫影工作台') }}</option></select></label><p class="muted">{{ tr('密钥可调用平台可用模型，按账户余额结算。当前不提供单独的模型限制或到期设置。') }}</p><p v-if="createError" role="alert" class="console-error">{{ createError }}</p><footer><AppButton variant="secondary" :disabled="creating" @click="keyDialog?.requestClose()">{{ tr('取消') }}</AppButton><AppButton type="submit" variant="primary" :loading="creating">{{ tr('创建') }}</AppButton></footer></form></AppDialog>
  <AppDialog class="console-dialog" :model-value="Boolean(secret)" :title="tr('请保存 API Key')" width="560px" :close-on-click-modal="false" @update:model-value="value=>{if(!value)secret=''}"><p>{{ tr('完整密钥仅显示一次，请妥善保存。') }}</p><code class="key-secret">{{ secret }}</code><div class="console-inline"><AppButton variant="primary" @click="copy(secret)"><Copy :size="16"/>{{ tr('复制密钥') }}</AppButton><AppButton variant="secondary" @click="secret=''">{{ tr('已保存，关闭') }}</AppButton></div></AppDialog>
 </ConsolePage>
</template>
