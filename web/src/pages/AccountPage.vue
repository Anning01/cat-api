<script setup lang="ts">
import { useId, computed, onBeforeUnmount, ref, watch } from 'vue'
import AppDialog from '@/components/AppDialog.vue'
import { RefreshCw, ArrowUpRight } from 'lucide-vue-next'
import ConsolePage from '@/components/ConsolePage.vue'
import ConsoleTable from '@/components/ConsoleTable.vue'
import ConsolePreferences from '@/components/ConsolePreferences.vue'
import AppButton from '@/components/AppButton.vue'
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
async function showDetail(row:AccountRow){
 const current=++detailEpoch;selected.value=row;detailError.value=''
 if(props.section!=='orders')return
 detailBusy.value=true
 try{const result=await request<SingleResponse<AccountRow>>('/account/recharge/'+encodeURIComponent(row.out_trade_no!));if(current===detailEpoch)selected.value={...row,...result.data}}
 catch(cause){if(current===detailEpoch)detailError.value=cause instanceof Error?cause.message:tr('加载失败')}
 finally{if(current===detailEpoch)detailBusy.value=false}
}
function startRefund(row:AccountRow){refundOrder.value=row;refundReason.value='';refundError.value=''}
async function refund(){
 if(!refundOrder.value||refundBusy.value)return
 refundBusy.value=true;refundError.value=''
 try{await request('/account/orders/'+encodeURIComponent(refundOrder.value.out_trade_no!)+'/refund',{method:'POST',body:JSON.stringify({reason:refundReason.value.trim()})});refundOrder.value=undefined;notice.success(tr('退款请求已提交'));await Promise.all([load(),auth.refreshMe()]);if(selected.value)await showDetail(selected.value)}catch(cause){refundError.value=cause instanceof Error?cause.message:tr('退款失败')}finally{refundBusy.value=false}
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
 <ConsolePage :title="tr(heading.title)" :description="tr(heading.description)">
  <template #actions><AppButton variant="secondary" :loading="loading" @click="load"><RefreshCw :size="16"/>{{ tr('刷新') }}</AppButton><AppButton v-if="section==='profile'" variant="secondary" @click="nickname=name;profileError='';editOpen=true">{{ tr('编辑资料') }}</AppButton><AppButton v-if="section==='orders'" variant="primary" @click="rechargeOpen=true">{{ tr('充值') }}</AppButton><AppButton v-if="section==='billing'&&auth.isSuperAdmin&&scope==='all'" variant="secondary" :loading="exportBusy" :disabled="loading||!data" @click="exportCSV">{{ tr('导出当前筛选') }}</AppButton></template>
  <p v-if="error" class="console-error" role="alert">{{ error }} <button @click="load">{{ tr('重试') }}</button></p>
  <template v-if="section==='profile'">
   <div class="console-summary account-balance-band"><div><span>{{ tr('可用余额') }}</span><strong>¥ {{ money(auth.balance) }}</strong></div><div class="account-balance-actions"><AppButton variant="primary" size="lg" @click="rechargeOpen=true">{{ tr('立即充值') }}<ArrowUpRight :size="16"/></AppButton><RouterLink to="/orders">{{ tr('查看充值订单') }}</RouterLink></div><div><span>{{ tr('累计消费') }}</span><strong>¥ {{ money(auth.totalCost) }}</strong></div><RouterLink to="/billing">{{ tr('查看消费账单') }}</RouterLink></div>
   <div class="profile-grid"><section class="console-section"><div class="section-heading"><h2>{{ tr('个人资料') }}</h2><AppButton @click="nickname=name;profileError='';editOpen=true">{{ tr('编辑昵称') }}</AppButton></div><div class="profile-identity"><div class="profile-avatar"><AppAvatar :name="name" :src="auth.user?.avatar_url" :size="72"/><label :for="formId+'-field-1'" class="upload-avatar">{{ tr('更换头像') }}<input name="field-1" :id="formId+'-field-1'" type="file" accept="image/png,image/jpeg,image/webp" :disabled="profileBusy" @change="avatar"/></label><span v-if="profileBusy" role="status" class="muted">{{ tr('处理中…') }}</span></div><dl class="detail-fields"><div><dt>{{ tr('昵称') }}</dt><dd>{{ name }}</dd></div><div><dt>{{ tr('用户名') }}</dt><dd>{{ auth.user?.username }}</dd></div><div><dt>{{ tr('用户编号') }}</dt><dd>#{{ auth.user?.id }}</dd></div><div><dt>{{ tr('创建时间') }}</dt><dd>{{ dateTime(auth.user?.created_at) }}</dd></div><div><dt>{{ tr('身份') }}</dt><dd><AppStatusBadge>{{ tr(auth.isSuperAdmin?'超级管理员':'普通用户') }}</AppStatusBadge></dd></div></dl></div></section><section class="console-section"><div class="section-heading"><h2>{{ tr('偏好设置') }}</h2></div><ConsolePreferences expanded/><p class="muted">{{ tr('语言和外观只影响你的界面，不改变平台设置。') }}</p><div class="preference-note"><strong>{{ tr('金额显示') }}</strong><span class="muted">{{ tr('账单明细保留实际计费精度。') }}</span></div></section></div>
   <section class="console-section"><div class="section-heading"><h2>{{ tr('账户安全') }}</h2><RouterLink to="/platform/keys">{{ tr('管理 API Key') }}</RouterLink></div><div class="security-row"><div><strong>{{ tr('登录方式') }}</strong><p class="muted">{{ tr(auth.provider==='password'?'密码登录':'器灵扫码登录') }}</p></div><AppStatusBadge>{{ tr(auth.qilingBound?'已绑定器灵':'独立账户') }}</AppStatusBadge></div><form v-if="auth.provider==='password'" class="console-filterbar" @submit.prevent="changePassword"><label :for="formId+'-field-2'">{{ tr('当前密码') }}<input name="field-2" :id="formId+'-field-2'" v-model="oldPassword" type="password" autocomplete="current-password" required/></label><label :for="formId+'-field-3'">{{ tr('新密码') }}<input name="field-3" :id="formId+'-field-3'" v-model="newPassword" type="password" autocomplete="new-password" minlength="8" required/></label><AppButton type="submit" variant="secondary" :loading="profileBusy">{{ tr('修改密码') }}</AppButton></form><div v-if="auth.provider==='qiling'&&!auth.qilingBound" class="security-row"><div><strong>{{ tr('器灵账号') }}</strong><p class="muted">{{ tr('绑定后可使用器灵扫码登录此账户，保留现有余额和记录。') }}</p></div><AppButton variant="secondary" @click="bindOpen=true">{{ tr('绑定账号') }}</AppButton></div><p v-if="profileError&&!editOpen" role="alert" class="console-error">{{ profileError }}</p></section>
   <footer class="console-legal"><a href="/api/auth/legal/terms" target="_blank" rel="noopener">{{ tr('用户协议') }}</a><a href="/api/auth/legal/privacy" target="_blank" rel="noopener">{{ tr('隐私政策') }}</a><a href="/api/auth/legal/privacy#account-data-requests" target="_blank" rel="noopener">{{ tr('账号与数据申请') }}</a></footer>
  </template>
  <template v-else>
   <div v-if="auth.isSuperAdmin" class="console-tabs" role="group" :aria-label="tr('查看范围')"><button v-for="view in [{value:'all',label:'全平台'},{value:'mine',label:'我的'}]" :key="view.value" :class="{'is-active':scope===view.value}" :aria-pressed="scope===view.value" @click="scope=view.value;data=undefined;apply()">{{ tr(view.label) }}</button></div>
   <search><form class="console-filterbar" @submit.prevent="apply"><label :for="formId+'-field-4'" v-if="section==='orders'">{{ tr('搜索') }}<input name="field-4" :id="formId+'-field-4'" v-model="search" type="search" autocorrect="off" :placeholder="tr('订单号或用户')"/></label><label :for="formId+'-field-5'" v-if="section==='orders'">{{ tr('订单状态') }}<select name="field-5" :id="formId+'-field-5'" v-model="status"><option value="">{{ tr('全部状态') }}</option><option v-for="(text,key) in orderLabels" :key="key" :value="key">{{ tr(text) }}</option></select></label><label :for="formId+'-field-6'" v-if="auth.isSuperAdmin&&scope==='all'">{{ tr('账户用户') }}<select name="field-6" :id="formId+'-field-6'" v-model="accountId"><option value="">{{ tr('全部用户') }}</option><option v-for="user in parties" :key="user.id" :value="user.id">{{ user.name }} · #{{ user.id }}</option></select></label><label :for="formId+'-field-7'" v-if="section==='billing'&&auth.isSuperAdmin&&scope==='all'">{{ tr('操作用户') }}<select name="field-7" :id="formId+'-field-7'" v-model="actorId"><option value="">{{ tr('全部用户') }}</option><option v-for="user in parties" :key="user.id" :value="user.id">{{ user.name }} · #{{ user.id }}</option></select></label><label :for="formId+'-field-8'">{{ tr('开始日期') }}<input name="field-8" :id="formId+'-field-8'" v-model="start" type="date" :max="end||undefined"/></label><label :for="formId+'-field-9'">{{ tr('结束日期') }}<input name="field-9" :id="formId+'-field-9'" v-model="end" type="date" :min="start||undefined"/></label><AppButton type="submit" variant="primary" :disabled="loading">{{ tr('查询') }}</AppButton><AppButton variant="secondary" @click="reset">{{ tr('重置') }}</AppButton></form></search>
   <div v-if="data?.summary" class="console-summary"><div><span>{{ tr('实际消费') }}</span><strong>¥ {{ money(data.summary.total_cost) }}</strong></div><div><span>{{ tr('计费记录') }}</span><strong>{{ data.summary.total_transactions }}</strong></div><div><span>{{ tr('查看范围') }}</span><strong class="summary-text">{{ tr(auth.isSuperAdmin&&scope==='all'?'全平台':'我的账户') }}</strong></div></div>
   <section class="console-table-panel" :aria-busy="loading"><div class="console-table-toolbar"><h2>{{ tr(section==='orders'?'订单列表':'消费明细') }} <small>{{ tr('共 {p0} 条',{p0:data?.pagination.total??'—'}) }}</small></h2><span class="muted">{{ tr('时间：北京时间（UTC+8）') }}</span></div><ConsoleTable :caption="tr(section==='orders'?'订单列表':'消费明细')"><thead><tr><th scope="col">{{ tr(section==='orders'?'订单号':'流水编号') }}</th><th scope="col" v-if="auth.isSuperAdmin&&scope==='all'">{{ tr('用户') }}</th><th scope="col" v-if="section==='billing'">{{ tr('类别') }}</th><th scope="col" class="numeric">{{ tr(section==='orders'?'充值金额':'实际扣费') }}</th><th scope="col" v-if="section==='billing'" class="numeric">{{ tr('扣后余额') }}</th><th scope="col" v-else>{{ tr('状态') }}</th><th scope="col">{{ tr('创建时间') }}</th><th scope="col" v-if="section==='orders'">{{ tr('支付时间') }}</th><th scope="col" class="row-actions">{{ tr('操作') }}</th></tr></thead><tbody><tr v-for="row in data?.items" :key="row.id"><th scope="row"><button class="table-link" @click="showDetail(row)">{{ section==='orders'?row.out_trade_no:'#'+row.id }}</button></th><td v-if="auth.isSuperAdmin&&scope==='all'">{{ row.user_name||row.nickname||row.username||row.user_id||'—' }}</td><td v-if="section==='billing'">{{ label(row.billing_type,billingLabels) }}</td><td class="numeric">¥ {{ money(section==='orders'?row.amount:row.cost) }}</td><td v-if="section==='billing'" class="numeric" :class="{'text-danger':Number(row.balance_after)<0}">{{ row.balance_after==null?'—':'¥ '+money(row.balance_after) }}</td><td v-else><AppStatusBadge :tone="orderTone(String(row.status))">{{ label(String(row.status),orderLabels) }}</AppStatusBadge></td><td class="date-cell">{{ dateTime(row.created_at) }}</td><td v-if="section==='orders'" class="date-cell">{{ dateTime(row.paid_at) }}</td><td class="row-actions"><AppButton size="sm" @click="showDetail(row)">{{ tr('详情') }}</AppButton><AppButton v-if="section==='orders'&&auth.isSuperAdmin&&['paid','refunding'].includes(String(row.status))" size="sm" :variant="row.status==='paid'?'danger':'ghost'" @click="row.status==='refunding'?showDetail(row):startRefund(row)">{{ tr(row.status==='refunding'?'查询退款':'退款') }}</AppButton></td></tr></tbody></ConsoleTable><div v-if="loading&&!data" class="console-skeleton" role="status">{{ tr('正在加载…') }}<i v-for="n in 5" :key="n"/></div><div v-else-if="!data?.items.length&&!error" class="console-empty"><h3>{{ tr('暂无记录') }}</h3><p>{{ tr('可以调整日期和筛选条件后重试。') }}</p><AppButton variant="secondary" @click="reset">{{ tr('清空筛选') }}</AppButton></div><AppPagination :page="page" :page-size="pageSize" :total="data?.pagination.total??0" @page-change="value=>{page=value;load()}" @size-change="value=>{pageSize=value;apply()}"/></section>
  </template>
  <AppDialog ref="editDialog" v-model="editOpen" class="console-dialog" :title="tr('编辑昵称')" guard-changes width="440px" :show-close="!profileBusy" :close-on-click-modal="!profileBusy" :close-on-press-escape="!profileBusy"><form class="console-form" @submit.prevent="saveProfile"><label :for="formId+'-field-10'">{{ tr('昵称') }}<input name="field-10" :id="formId+'-field-10'" v-model="nickname" autofocus maxlength="100" required/></label><p v-if="profileError" class="console-error" role="alert">{{ profileError }}</p><footer><AppButton variant="secondary" :disabled="profileBusy" @click="editDialog?.requestClose()">{{ tr('取消') }}</AppButton><AppButton type="submit" variant="primary" :loading="profileBusy">{{ tr('保存') }}</AppButton></footer></form></AppDialog>
  <AppDialog v-model="bindOpen" class="console-dialog" :title="tr('绑定器灵账号')" width="440px"><QilingLogin bind @bound="auth.refreshMe();bindOpen=false"/></AppDialog>
  <AppDialog drawer class="console-drawer" :model-value="Boolean(selected)" :title="tr(section==='orders'?'订单详情':'账单详情')" size="min(640px, 100vw)" @update:model-value="value=>{if(!value){selected=undefined;++detailEpoch;detailBusy=false}}"><p v-if="detailError" role="alert" class="console-error">{{ detailError }}<button @click="selected&&showDetail(selected)">{{ tr('重试') }}</button></p><p v-if="detailBusy" role="status" class="console-empty">{{ tr('正在加载…') }}</p><template v-else-if="selected&&!detailError"><div class="detail-amount">¥ {{ money(section==='orders'?selected.amount:selected.cost) }}</div><AppStatusBadge v-if="section==='orders'" :tone="orderTone(String(selected.status))">{{ label(String(selected.status),orderLabels) }}</AppStatusBadge><dl class="detail-fields"><div><dt>{{ tr(section==='orders'?'订单号':'流水编号') }}</dt><dd>{{ selected.out_trade_no||'#'+selected.id }}</dd></div><div><dt>{{ tr('创建时间') }}</dt><dd>{{ dateTime(selected.created_at) }}</dd></div><template v-if="section==='orders'"><div><dt>{{ tr('支付时间') }}</dt><dd>{{ dateTime(selected.paid_at) }}</dd></div><div><dt>{{ tr('支付方式') }}</dt><dd>{{ selected.payment_method==='wechat_native'?tr('微信支付'):selected.payment_method||'—' }}</dd></div><div><dt>{{ tr('交易编号') }}</dt><dd>{{ selected.transaction_id||'—' }}</dd></div><div><dt>{{ tr('退款编号') }}</dt><dd>{{ selected.refund_id||'—' }}</dd></div><div><dt>{{ tr('退款时间') }}</dt><dd>{{ dateTime(selected.refunded_at) }}</dd></div><div><dt>{{ tr('退款原因') }}</dt><dd>{{ selected.refund_reason||'—' }}</dd></div></template><template v-else><div><dt>{{ tr('类别') }}</dt><dd>{{ label(selected.billing_type,billingLabels) }}</dd></div><div><dt>{{ tr('扣后余额') }}</dt><dd>{{ selected.balance_after==null?'—':'¥ '+money(selected.balance_after) }}</dd></div><div><dt>{{ tr('关联账单号') }}</dt><dd>{{ selected.usage_record_id??'—' }}</dd></div><div v-for="(value,key) in selected.usage" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></div><p v-if="!Object.keys(selected.usage||{}).length" class="muted">{{ tr('历史记录未提供详细用量。') }}</p></template></dl></template></AppDialog>
  <AppDialog class="console-dialog" :model-value="Boolean(refundOrder)" :title="tr('确认原路退款')" width="480px" :show-close="!refundBusy" :close-on-click-modal="!refundBusy" :close-on-press-escape="!refundBusy" @update:model-value="value=>{if(!value&&!refundBusy)refundOrder=undefined}"><form class="console-form" @submit.prevent="refund"><p>{{ refundOrder?.out_trade_no }}</p><p>{{ tr('退款金额') }} <strong>¥ {{ money(refundOrder?.amount,2) }}</strong></p><p class="muted">{{ tr('原路退回支付账户，并扣回对应账户余额。提交后以退款状态为准。') }}</p><label :for="formId+'-field-11'">{{ tr('退款原因') }}<textarea name="field-11" :id="formId+'-field-11'" v-model="refundReason" maxlength="255" required rows="3"/></label><p v-if="refundError" class="console-error" role="alert">{{ refundError }}</p><footer><AppButton variant="secondary" :disabled="refundBusy" @click="refundOrder=undefined">{{ tr('取消') }}</AppButton><AppButton type="submit" variant="danger" :loading="refundBusy">{{ tr('确认退款') }}</AppButton></footer></form></AppDialog>
 </ConsolePage>
</template>
