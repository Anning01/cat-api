<script setup lang="ts">
import { useId, computed, onBeforeUnmount, ref, watch } from 'vue'
import AppDialog from '@/components/AppDialog.vue'
import { RefreshCw, ArrowUpRight } from 'lucide-vue-next'
import ConsolePage from '@/components/ConsolePage.vue'
import ConsoleTable from '@/components/ConsoleTable.vue'
import ConsolePreferences from '@/components/ConsolePreferences.vue'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppStatusBadge from '@/components/AppStatusBadge.vue'
import AppPagination from '@/components/AppPagination.vue'
import QilingLogin from '@/features/auth/QilingLogin.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { API_BASE, getAuthToken, request } from '@/api'
import { tr } from '@/i18n'
import { money, dateTime, rechargeOpen, orderLabels, orderTone, billingLabels, label } from '@/shared/console'
import { notice } from '@/shared/notice'
import type { SingleResponse } from '@/types'
import type { AccountRow, AccountTable } from '@/features/account/types'

const props=defineProps<{section:'profile'|'orders'|'billing'}>()
const auth=useAuthStore()
const heading=computed(()=>({profile:{title:'个人中心',description:'管理个人资料、账户余额与偏好。'},orders:{title:'充值订单',description:'查看充值、到账与退款状态。'},billing:{title:'消费账单',description:'核对实际扣费、用量与账户余额。'}}[props.section]))
const name=computed(()=>auth.user?.nickname||auth.user?.username||'')
const data=ref<AccountTable>(),loading=ref(false),error=ref(''),page=ref(1),pageSize=ref(20)
const scope=ref(auth.isSuperAdmin?'all':'mine'),search=ref(''),status=ref(''),accountId=ref(''),actorId=ref(''),start=ref(''),end=ref('')
const parties=ref<{id:number;name:string}[]>([])
const editOpen=ref(false),nickname=ref(''),profileBusy=ref(false),profileError=ref(''),oldPassword=ref(''),newPassword=ref(''),bindOpen=ref(false)
const selected=ref<AccountRow>(),detailBusy=ref(false),detailError=ref(''),refundOrder=ref<AccountRow>(),refundReason=ref(''),refundBusy=ref(false),refundError=ref(''),exportBusy=ref(false)
let epoch=0,detailEpoch=0
function filters(){
 const query=new URLSearchParams()
 for(const [key,value] of Object.entries({search:props.section==='orders'?search.value:'',status:props.section==='orders'?status.value:'',start_date:start.value,end_date:end.value}))if(value)query.set(key,value)
 if(auth.isSuperAdmin&&scope.value==='all'){if(accountId.value)query.set('account_user_id',accountId.value);if(props.section==='billing'&&actorId.value)query.set('user_id',actorId.value)}
 else if(auth.user)query.set('account_user_id',String(auth.user.id))
 return query
}
async function load(){
 const current=++epoch;loading.value=true;error.value=''
 try{
  if(props.section==='profile'){await auth.refreshMe();return}
  if(start.value&&end.value&&start.value>end.value)throw new Error(tr('开始日期不能晚于结束日期'))
  const query=filters();query.set('page',String(page.value));query.set('page_size',String(pageSize.value))
  const path=props.section==='orders'?'/account/orders':auth.isSuperAdmin&&scope.value==='all'?'/billing/statements':'/billing/mine'
  const result=await request<SingleResponse<AccountTable>>(path+'?'+query)
  if(current!==epoch)return
  data.value=result.data
  if(auth.isSuperAdmin&&!parties.value.length){try{const result=await request<SingleResponse<{users:{id:number;name:string}[]}>>('/billing/statements/parties');if(current===epoch)parties.value=result.data.users}catch{/* IDs and the current list remain usable. */}}
 }catch(cause){if(current===epoch)error.value=cause instanceof Error?cause.message:tr('加载失败')}
 finally{if(current===epoch)loading.value=false}
}
function apply(){page.value=1;void load()}
function reset(){search.value='';status.value='';accountId.value='';actorId.value='';start.value='';end.value='';apply()}
async function saveProfile(){
 if(profileBusy.value)return
 profileBusy.value=true;profileError.value=''
 try{await request('/auth/profile',{method:'PATCH',body:JSON.stringify({nickname:nickname.value.trim()})});await auth.refreshMe();editOpen.value=false;notice.success(tr('昵称已更新'))}
 catch(cause){profileError.value=cause instanceof Error?cause.message:tr('保存失败')}
 finally{profileBusy.value=false}
}
async function avatar(event:Event){
 const input=event.target as HTMLInputElement,file=input.files?.[0];if(!file||profileBusy.value)return
 const form=new FormData();form.append('file',file);profileBusy.value=true
 try{await request('/auth/avatar',{method:'POST',body:form});await auth.refreshMe();notice.success(tr('头像已更新'))}catch(cause){notice.error(cause instanceof Error?cause.message:tr('上传失败'))}finally{profileBusy.value=false;input.value=''}
}
async function changePassword(){
 if(profileBusy.value)return
 profileBusy.value=true;profileError.value=''
 try{await request('/auth/change-password',{method:'POST',body:JSON.stringify({old_password:oldPassword.value,new_password:newPassword.value})});oldPassword.value='';newPassword.value='';notice.success(tr('密码已修改'))}catch(cause){profileError.value=cause instanceof Error?cause.message:tr('修改失败')}finally{profileBusy.value=false}
}
async function showOrder(row:AccountRow){
 if(props.section!=='orders')return
 const current=++detailEpoch;selected.value=row;detailError.value=''
 detailBusy.value=true
 try{const result=await request<SingleResponse<AccountRow>>('/account/recharge/'+encodeURIComponent(row.out_trade_no!));if(current===detailEpoch)selected.value={...row,...result.data}}
 catch(cause){if(current===detailEpoch)detailError.value=cause instanceof Error?cause.message:tr('加载失败')}
 finally{if(current===detailEpoch)detailBusy.value=false}
}
const usageLabels:Record<string,string>={input_tokens:'输入 Tokens',output_tokens:'输出 Tokens',image_count:'图片数量',input_image_count:'参考图数量',seconds:'时长（秒）',duration_seconds:'时长（秒）',resolution:'分辨率',clarity:'清晰度',fps:'帧率',missing_usage:'用量缺失'}
function usageFields(row:AccountRow){return Object.entries(row.usage||{}).map(([key,value])=>({key,label:tr(usageLabels[key]||key),value:value==null?'—':typeof value==='boolean'?tr(value?'是':'否'):typeof value==='object'?JSON.stringify(value):String(value)}))}
function startRefund(row:AccountRow){refundOrder.value=row;refundReason.value='';refundError.value=''}
async function refund(){
 if(!refundOrder.value||refundBusy.value)return
 refundBusy.value=true;refundError.value=''
 try{await request('/account/orders/'+encodeURIComponent(refundOrder.value.out_trade_no!)+'/refund',{method:'POST',body:JSON.stringify({reason:refundReason.value.trim()})});refundOrder.value=undefined;notice.success(tr('退款请求已提交'));await Promise.all([load(),auth.refreshMe()]);if(selected.value)await showOrder(selected.value)}catch(cause){refundError.value=cause instanceof Error?cause.message:tr('退款失败')}finally{refundBusy.value=false}
}
async function exportCSV(){
 if(exportBusy.value)return
 exportBusy.value=true
 try{const query=filters();if(data.value?.snapshot_id!==undefined)query.set('snapshot_id',String(data.value.snapshot_id));const response=await fetch(API_BASE+'/billing/statements/export?'+query,{headers:{Authorization:'Bearer '+getAuthToken()}});if(!response.ok||!response.headers.get('content-type')?.includes('text/csv'))throw new Error(tr('导出失败，请重试'));const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='billing-statement.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(cause){notice.error(cause instanceof Error?cause.message:tr('导出失败'))}finally{exportBusy.value=false}
}
watch(()=>props.section,()=>{page.value=1;search.value='';status.value='';accountId.value='';actorId.value='';data.value=undefined;selected.value=undefined;start.value='';end.value='';void load()},{immediate:true})
onBeforeUnmount(()=>{++epoch;++detailEpoch})
const formId=useId()
const editDialog=ref<InstanceType<typeof AppDialog>>()
</script>
<template>
 <ConsolePage :title="tr(heading.title)" :description="tr(heading.description)" :class="['account-'+section,{'account-records':section!=='profile'}]">
  <template #actions><AppButton variant="secondary" :loading="loading" @click="load"><RefreshCw :size="16"/>{{ tr('刷新') }}</AppButton><AppButton v-if="section==='orders'" variant="primary" @click="rechargeOpen=true">{{ tr('充值') }}</AppButton><AppButton v-if="section==='billing'&&auth.isSuperAdmin&&scope==='all'" variant="secondary" :loading="exportBusy" :disabled="loading||!data" @click="exportCSV">{{ tr('导出当前筛选') }}</AppButton></template>
  <p v-if="error" class="console-error" role="alert">{{ error }} <button @click="load">{{ tr('重试') }}</button></p>
  <template v-if="section==='profile'">
   <div class="profile-layout">
    <div class="profile-account-column">
     <section class="profile-surface profile-account" :aria-label="tr('个人资料')">
      <div class="profile-account-heading"><AppAvatar :name="name" :src="auth.user?.avatar_url" :size="64"/><div><h2>{{ name||'—' }}</h2><AppStatusBadge>{{ tr(auth.isSuperAdmin?'超级管理员':'普通用户') }}</AppStatusBadge></div></div>
      <div class="profile-account-actions"><label :for="formId+'-field-1'" class="upload-avatar">{{ tr('更换头像') }}<input name="field-1" :id="formId+'-field-1'" type="file" accept="image/png,image/jpeg,image/webp" :disabled="profileBusy" @change="avatar"/></label><AppButton size="sm" variant="secondary" @click="nickname=name;profileError='';editOpen=true">{{ tr('编辑昵称') }}</AppButton></div>
      <span v-if="profileBusy" role="status" class="muted">{{ tr('处理中…') }}</span>
      <dl class="profile-facts"><div class="profile-username"><dt>{{ tr('用户名') }}</dt><dd>{{ auth.user?.username||'—' }}</dd></div><div><dt>{{ tr('用户编号') }}</dt><dd>#{{ auth.user?.id }}</dd></div><div><dt>{{ tr('创建时间') }}</dt><dd>{{ dateTime(auth.user?.created_at) }}</dd></div></dl>
     </section>
     <footer class="profile-legal"><a href="/api/auth/legal/terms" target="_blank" rel="noopener">{{ tr('用户协议') }}</a><a href="/api/auth/legal/privacy" target="_blank" rel="noopener">{{ tr('隐私政策') }}</a><a href="/api/auth/legal/privacy#account-data-requests" target="_blank" rel="noopener">{{ tr('账号与数据申请') }}</a></footer>
    </div>
    <div class="profile-workspace">
     <section class="profile-surface profile-wallet" :aria-label="tr('账户余额')">
      <div class="profile-wallet-main"><div><h2>{{ tr('可用余额') }}</h2><strong class="profile-balance" :class="{'text-danger':Number(auth.balance)<0}">¥ {{ money(auth.balance) }}</strong></div><AppButton variant="primary" size="lg" @click="rechargeOpen=true">{{ tr('立即充值') }}<ArrowUpRight :size="16"/></AppButton></div>
      <div class="profile-wallet-footer"><div class="profile-total"><span>{{ tr('累计消费') }}</span><strong>¥ {{ money(auth.totalCost) }}</strong></div><nav class="profile-money-links" :aria-label="tr('账户与费用')"><RouterLink to="/orders">{{ tr('充值订单') }}</RouterLink><RouterLink to="/billing">{{ tr('消费账单') }}</RouterLink></nav></div>
     </section>
     <section class="profile-surface profile-settings">
      <h2>{{ tr('偏好与安全') }}</h2>
      <ConsolePreferences expanded/>
      <div class="profile-setting-row"><div><strong>{{ tr('登录方式') }}</strong><p>{{ tr(auth.provider==='password'?'密码登录':'器灵扫码登录') }}</p></div><AppStatusBadge>{{ tr(auth.qilingBound?'已绑定器灵':'独立账户') }}</AppStatusBadge></div>
      <form v-if="auth.provider==='password'" class="profile-password-form" @submit.prevent="changePassword"><label :for="formId+'-field-2'">{{ tr('当前密码') }}<input name="field-2" :id="formId+'-field-2'" v-model="oldPassword" type="password" autocomplete="current-password" required/></label><label :for="formId+'-field-3'">{{ tr('新密码') }}<input name="field-3" :id="formId+'-field-3'" v-model="newPassword" type="password" autocomplete="new-password" minlength="8" required/></label><AppButton type="submit" variant="secondary" :loading="profileBusy">{{ tr('修改密码') }}</AppButton></form>
      <div v-if="auth.provider==='qiling'&&!auth.qilingBound" class="profile-setting-row"><div><strong>{{ tr('器灵账号') }}</strong><p>{{ tr('绑定后可使用器灵扫码登录此账户，保留现有余额和记录。') }}</p></div><AppButton size="sm" variant="secondary" @click="bindOpen=true">{{ tr('绑定账号') }}</AppButton></div>
      <div class="profile-setting-row profile-key-row"><strong>API Key</strong><RouterLink to="/platform/keys">{{ tr('管理 API Key') }} <ArrowUpRight :size="14" aria-hidden="true"/></RouterLink></div>
      <p v-if="profileError&&!editOpen" role="alert" class="console-error">{{ profileError }}</p>
     </section>
    </div>
   </div>
  </template>
  <template v-else>
   <search><form class="console-filterbar" @submit.prevent="apply"><label v-if="auth.isSuperAdmin" class="account-scope" :for="formId+'-scope'">{{ tr('查看范围') }}<AppSelect :id="formId+'-scope'" :model-value="scope" :ariaLabel="tr('查看范围')" :options="[{value:'all',label:tr('全平台')},{value:'mine',label:tr('我的')}]" @update:model-value="value=>{scope=value;data=undefined;apply()}"/></label><label :for="formId+'-field-4'" v-if="section==='orders'">{{ tr('搜索') }}<input name="field-4" :id="formId+'-field-4'" v-model="search" type="search" autocorrect="off" :placeholder="tr('订单号或用户')"/></label><label :for="formId+'-field-5'" v-if="section==='orders'">{{ tr('订单状态') }}<AppSelect :id="formId+'-field-5'" v-model="status" :ariaLabel="tr('订单状态')" :options="[{value:'',label:tr('全部状态')},...Object.entries(orderLabels).map(([value,text])=>({value,label:tr(text)}))]"/></label><label :for="formId+'-field-6'" v-if="auth.isSuperAdmin&&scope==='all'">{{ tr('账户用户') }}<AppSelect :id="formId+'-field-6'" v-model="accountId" :ariaLabel="tr('账户用户')" :options="[{value:'',label:tr('全部用户')},...parties.map(user=>({value:String(user.id),label:user.name+' · #'+user.id}))]" searchable/></label><label :for="formId+'-field-7'" v-if="section==='billing'&&auth.isSuperAdmin&&scope==='all'">{{ tr('操作用户') }}<AppSelect :id="formId+'-field-7'" v-model="actorId" :ariaLabel="tr('操作用户')" :options="[{value:'',label:tr('全部用户')},...parties.map(user=>({value:String(user.id),label:user.name+' · #'+user.id}))]" searchable/></label><label :for="formId+'-field-8'">{{ tr('开始日期') }}<input name="field-8" :id="formId+'-field-8'" v-model="start" type="date" :max="end||undefined"/></label><label :for="formId+'-field-9'">{{ tr('结束日期') }}<input name="field-9" :id="formId+'-field-9'" v-model="end" type="date" :min="start||undefined"/></label><AppButton type="submit" variant="primary" :disabled="loading">{{ tr('查询') }}</AppButton><AppButton variant="secondary" @click="reset">{{ tr('重置') }}</AppButton></form></search>
   <section class="console-table-panel is-compact" :class="{'has-records':Boolean(data?.items.length)}" :aria-busy="loading">
    <div class="console-table-toolbar"><div class="account-list-heading"><h2>{{ tr(section==='orders'?'订单列表':'消费明细') }} <small v-if="!data?.summary">{{ tr('共 {p0} 条',{p0:data?.pagination.total??'—'}) }}</small></h2><dl v-if="data?.summary" class="billing-summary"><div><dt>{{ tr('实际消费') }}</dt><dd>¥ {{ money(data.summary.total_cost) }}</dd></div><div><dt>{{ tr('计费记录') }}</dt><dd>{{ data.summary.total_transactions }}</dd></div></dl></div><span class="muted">{{ tr('时间：北京时间（UTC+8）') }}</span></div>
    <ConsoleTable :caption="tr(section==='orders'?'订单列表':'消费明细')" :class="{'billing-table':section==='billing'}">
     <thead><tr>
      <th scope="col">{{ tr(section==='orders'?'订单号':'流水 / 创建时间') }}</th>
      <th scope="col" v-if="auth.isSuperAdmin&&scope==='all'">{{ tr('用户') }}</th>
      <th scope="col" v-if="section==='billing'">{{ tr('类别') }}</th>
      <th scope="col" v-if="section==='billing'">{{ tr('用量') }}</th>
      <th scope="col" class="numeric">{{ tr(section==='orders'?'充值金额':'实际扣费') }}</th>
      <th scope="col" v-if="section==='billing'" class="numeric">{{ tr('扣后余额') }}</th><th scope="col" v-else>{{ tr('状态') }}</th>
      <th scope="col" v-if="section==='billing'">{{ tr('关联账单号') }}</th>
      <template v-else><th scope="col">{{ tr('创建时间') }}</th><th scope="col">{{ tr('支付时间') }}</th><th scope="col" class="row-actions">{{ tr('操作') }}</th></template>
     </tr></thead>
     <tbody><tr v-for="row in data?.items" :key="row.id">
      <th scope="row"><button v-if="section==='orders'" class="table-link" @click="showOrder(row)">{{ row.out_trade_no }}</button><div v-else class="billing-identity"><strong>#{{ row.id }}</strong><small>{{ dateTime(row.created_at) }}</small></div></th>
      <td v-if="auth.isSuperAdmin&&scope==='all'">{{ row.user_name||row.nickname||row.username||row.user_id||'—' }}</td>
      <td v-if="section==='billing'">{{ label(row.billing_type,billingLabels) }}</td>
      <td v-if="section==='billing'"><dl v-if="Object.keys(row.usage||{}).length" class="billing-usage"><div v-for="field in usageFields(row)" :key="field.key"><dt>{{ field.label }}</dt><dd>{{ field.value }}</dd></div></dl><span v-else class="muted">{{ tr('历史记录未提供详细用量。') }}</span></td>
      <td class="numeric">¥ {{ money(section==='orders'?row.amount:row.cost) }}</td>
      <td v-if="section==='billing'" class="numeric" :class="{'text-danger':Number(row.balance_after)<0}">{{ row.balance_after==null?'—':'¥ '+money(row.balance_after) }}</td><td v-else><AppStatusBadge :tone="orderTone(String(row.status))">{{ label(String(row.status),orderLabels) }}</AppStatusBadge></td>
      <td v-if="section==='billing'"><code>{{ row.usage_record_id??'—' }}</code></td>
      <template v-else><td class="date-cell">{{ dateTime(row.created_at) }}</td><td class="date-cell">{{ dateTime(row.paid_at) }}</td><td class="row-actions"><AppButton size="sm" @click="showOrder(row)">{{ tr('详情') }}</AppButton><AppButton v-if="auth.isSuperAdmin&&['paid','refunding'].includes(String(row.status))" size="sm" :variant="row.status==='paid'?'danger':'ghost'" @click="row.status==='refunding'?showOrder(row):startRefund(row)">{{ tr(row.status==='refunding'?'查询退款':'退款') }}</AppButton></td></template>
     </tr></tbody>
    </ConsoleTable>
    <div v-if="loading&&!data" class="console-skeleton" role="status">{{ tr('正在加载…') }}<i v-for="n in 5" :key="n"/></div><div v-else-if="!data?.items.length&&!error" class="console-empty"><h3>{{ tr('暂无记录') }}</h3><p>{{ tr('可以调整日期和筛选条件后重试。') }}</p><AppButton variant="secondary" @click="reset">{{ tr('清空筛选') }}</AppButton></div>
    <AppPagination :page="page" :page-size="pageSize" :total="data?.pagination.total??0" @page-change="value=>{page=value;load()}" @size-change="value=>{pageSize=value;apply()}"/>
   </section>
  </template>
  <AppDialog ref="editDialog" v-model="editOpen" class="console-dialog" :title="tr('编辑昵称')" guard-changes width="440px" :show-close="!profileBusy" :close-on-click-modal="!profileBusy" :close-on-press-escape="!profileBusy"><form class="console-form" @submit.prevent="saveProfile"><label :for="formId+'-field-10'">{{ tr('昵称') }}<input name="field-10" :id="formId+'-field-10'" v-model="nickname" autofocus maxlength="100" required/></label><p v-if="profileError" class="console-error" role="alert">{{ profileError }}</p><footer><AppButton variant="secondary" :disabled="profileBusy" @click="editDialog?.requestClose()">{{ tr('取消') }}</AppButton><AppButton type="submit" variant="primary" :loading="profileBusy">{{ tr('保存') }}</AppButton></footer></form></AppDialog>
  <AppDialog v-model="bindOpen" class="console-dialog" :title="tr('绑定器灵账号')" width="440px"><QilingLogin bind @bound="auth.refreshMe();bindOpen=false"/></AppDialog>
  <AppDialog v-if="section==='orders'" drawer class="console-drawer" :model-value="Boolean(selected)" :title="tr('订单详情')" size="min(640px,100vw)" @update:model-value="value=>{if(!value){selected=undefined;++detailEpoch;detailBusy=false}}">
   <p v-if="detailError" role="alert" class="console-error">{{ detailError }}<button @click="selected&&showOrder(selected)">{{ tr('重试') }}</button></p><p v-if="detailBusy" role="status" class="console-empty">{{ tr('正在加载…') }}</p>
   <template v-else-if="selected&&!detailError"><div class="detail-amount">¥ {{ money(selected.amount) }}</div><AppStatusBadge :tone="orderTone(String(selected.status))">{{ label(String(selected.status),orderLabels) }}</AppStatusBadge>
    <dl class="detail-fields"><div><dt>{{ tr('订单号') }}</dt><dd>{{ selected.out_trade_no||'#'+selected.id }}</dd></div><div><dt>{{ tr('创建时间') }}</dt><dd>{{ dateTime(selected.created_at) }}</dd></div><div><dt>{{ tr('支付时间') }}</dt><dd>{{ dateTime(selected.paid_at) }}</dd></div><div><dt>{{ tr('支付方式') }}</dt><dd>{{ selected.payment_method==='wechat_native'?tr('微信支付'):selected.payment_method||'—' }}</dd></div><div><dt>{{ tr('交易编号') }}</dt><dd>{{ selected.transaction_id||'—' }}</dd></div><div><dt>{{ tr('退款编号') }}</dt><dd>{{ selected.refund_id||'—' }}</dd></div><div><dt>{{ tr('退款时间') }}</dt><dd>{{ dateTime(selected.refunded_at) }}</dd></div><div><dt>{{ tr('退款原因') }}</dt><dd>{{ selected.refund_reason||'—' }}</dd></div></dl>
   </template>
  </AppDialog>
  <AppDialog class="console-dialog" :model-value="Boolean(refundOrder)" :title="tr('确认原路退款')" width="480px" :show-close="!refundBusy" :close-on-click-modal="!refundBusy" :close-on-press-escape="!refundBusy" @update:model-value="value=>{if(!value&&!refundBusy)refundOrder=undefined}"><form class="console-form" @submit.prevent="refund"><p>{{ refundOrder?.out_trade_no }}</p><p>{{ tr('退款金额') }} <strong>¥ {{ money(refundOrder?.amount,2) }}</strong></p><p class="muted">{{ tr('原路退回支付账户，并扣回对应账户余额。提交后以退款状态为准。') }}</p><label :for="formId+'-field-11'">{{ tr('退款原因') }}<textarea name="field-11" :id="formId+'-field-11'" v-model="refundReason" maxlength="255" required rows="3"/></label><p v-if="refundError" class="console-error" role="alert">{{ refundError }}</p><footer><AppButton variant="secondary" :disabled="refundBusy" @click="refundOrder=undefined">{{ tr('取消') }}</AppButton><AppButton type="submit" variant="danger" :loading="refundBusy">{{ tr('确认退款') }}</AppButton></footer></form></AppDialog>
 </ConsolePage>
</template>

<style scoped>

.account-profile { padding:20px 24px 32px; }
.account-profile :deep(.console-page-header) { min-height:0; align-items:center; margin-bottom:16px; padding-bottom:0; border:0; }
.account-profile :deep(.console-page-heading) { display:flex; align-items:baseline; flex-wrap:wrap; gap:4px 16px; }
.account-profile :deep(.console-page-heading h1) { margin:0; }
.account-profile :deep(.console-page-heading p) { font-size:13px; }
.profile-layout { display:grid; grid-template-columns:300px minmax(0,1fr); align-items:start; gap:20px; }
.profile-workspace { display:grid; gap:16px; min-width:0; }
.profile-surface { min-width:0; padding:20px; border:1px solid var(--app-border); border-radius:12px; background:var(--app-surface); }
.profile-account-heading { display:flex; align-items:center; gap:14px; }
.profile-account-heading > div { min-width:0; }
.profile-account-heading h2 { margin:0 0 6px; font-size:18px; overflow-wrap:anywhere; }
.profile-account-actions { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin-block:16px 20px; }
.profile-account-actions .upload-avatar { min-height:32px; border-color:var(--app-border); background:var(--app-surface-muted); }
.profile-facts { display:grid; grid-template-columns:70px minmax(0,1fr); gap:16px 12px; margin:0; }
.profile-facts > div { min-width:0; }
.profile-facts .profile-username { grid-column:1 / -1; }
.profile-facts dt { margin-bottom:5px; color:var(--app-text-secondary); font-size:12px; }
.profile-facts dd { margin:0; color:var(--app-text); font-size:12px; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.profile-username dd { font-family:ui-monospace,monospace; line-height:1.6; }
.profile-legal { display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:12px; padding-inline:4px; font-size:11px; }
.profile-legal a { color:var(--app-text-secondary); }
.profile-wallet-main { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:16px; }
.profile-wallet-main h2 { font-size:13px; font-weight:500; color:var(--app-text-secondary); }
.profile-balance { display:block; margin-top:6px; font-size:32px; font-weight:650; line-height:1.25; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.profile-wallet-footer { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-top:18px; padding-top:14px; border-top:1px solid var(--app-border); }
.profile-total { display:flex; align-items:baseline; flex-wrap:wrap; gap:8px; font-size:12px; color:var(--app-text-secondary); }
.profile-total strong { color:var(--app-text); font-size:15px; font-weight:600; font-variant-numeric:tabular-nums; }
.profile-money-links { display:flex; flex-wrap:wrap; gap:16px; font-size:13px; }
.profile-settings > h2 { margin-bottom:10px; font-size:15px; }
.profile-settings :deep(.console-preferences.is-expanded label) { min-height:48px; font-size:13px; }
.profile-settings :deep(.console-preferences.is-expanded .app-select) { width:176px; min-width:150px; max-width:176px; }
.profile-setting-row { display:flex; align-items:center; justify-content:space-between; gap:16px; padding-block:14px; border-bottom:1px solid var(--app-border); }
.profile-setting-row strong { font-size:13px; font-weight:500; }
.profile-setting-row p { margin:4px 0 0; color:var(--app-text-secondary); font-size:12px; }
.profile-key-row { border-bottom:0; padding-bottom:0; }
.profile-key-row a { display:inline-flex; align-items:center; gap:5px; font-size:13px; }
.profile-password-form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); align-items:end; gap:12px; padding-block:14px; border-bottom:1px solid var(--app-border); }
.profile-password-form label { display:grid; gap:7px; min-width:0; font-size:12px; color:var(--app-text-secondary); }
.profile-password-form input { width:100%; }
.profile-password-form .app-button { grid-column:1 / -1; justify-self:start; }
@media(max-width:1000px) { .profile-layout { grid-template-columns:260px minmax(0,1fr); gap:16px; } .profile-surface { padding:16px; } .profile-facts { grid-template-columns:60px minmax(0,1fr); } }
@media(max-width:800px) { .profile-layout { grid-template-columns:minmax(0,1fr); } .profile-account-column { min-width:0; } }
@media(max-width:767px) { .account-profile { padding:16px; } .account-profile :deep(.console-page-heading p) { display:none; } .profile-password-form { grid-template-columns:minmax(0,1fr); } .profile-balance { font-size:28px; } }
@media(pointer:coarse) { .profile-account-actions .upload-avatar { min-height:44px; } }

.account-records { display:flex; flex-direction:column; height:100%; min-height:100%; }
.account-records > search,.account-records :deep(.console-page-header) { flex-shrink:0; }
.account-records .console-filterbar { gap:8px; margin-bottom:12px; }
.account-records .console-filterbar > label { flex:1 1 116px; min-width:0; max-width:none; gap:4px; font-size:12px; }
.account-records .console-filterbar > label:has(input[type=search]) { flex:1.4 1 160px; }
.account-records .console-filterbar > label:has(input[type=date]) { flex:1 1 136px; }
.account-records .console-filterbar > .account-scope { flex:0 0 104px; }
.account-records .console-table-panel { display:flex; flex:1; flex-direction:column; min-height:240px; margin-bottom:0; }
.account-records .console-table-toolbar,.account-records :deep(.app-pagination) { flex-shrink:0; }
.account-records :deep(.console-table-scroll) { flex:1; min-height:0; max-height:none; }
.account-records :deep(.console-data-table) { min-width:880px; }
.account-records .console-table-panel:not(.has-records) :deep(.console-table-scroll) { flex:none; }
.account-records .console-empty,.account-records .console-skeleton { flex:1; }
@media(min-width:768px) and (max-width:1199px) {
 .account-records .console-filterbar { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); }
 .account-records .console-filterbar > .app-button { justify-self:start; }
}
@media(max-width:767px) {
 .account-records { height:auto; }
 .account-records .console-filterbar { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); }
 .account-records .console-filterbar > .account-scope,.account-records .console-filterbar > label:has(input[type=search]) { grid-column:1 / -1; }
 .account-records .console-table-toolbar { gap:4px; }
 .account-records .console-table-toolbar > .muted { font-size:11px; }
 .account-records :deep(.console-table-scroll) { flex:none; max-height:65dvh; }
 .account-records :deep(.app-pagination) { flex-wrap:wrap; }
}

.account-list-heading { display:flex; align-items:center; flex-wrap:wrap; gap:8px 20px; min-width:0; }
.billing-summary { display:flex; align-items:baseline; flex-wrap:wrap; gap:4px 20px; margin:0; }
.billing-summary > div { display:inline-flex; align-items:baseline; gap:6px; }
.billing-summary dt { color:var(--app-text-secondary); font-size:12px; }
.billing-summary dd { margin:0; font-size:13px; font-weight:600; font-variant-numeric:tabular-nums; }

.billing-identity { min-width:150px; white-space:nowrap; }
.billing-identity strong { font-weight:500; }
.billing-identity small { display:block; margin-top:3px; color:var(--app-text-secondary); font-size:11px; font-weight:400; }
.billing-usage { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 12px; min-width:220px; margin:0; }
.billing-usage div { display:inline-flex; align-items:baseline; gap:6px; }
.billing-usage dt { color:var(--app-text-secondary); font-size:12px; white-space:nowrap; }
.billing-usage dd { margin:0; color:var(--app-text); font-size:12px; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
</style>
