<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElDialog } from 'element-plus'
import { Wallet, ArrowUpRight, RefreshCw, UserRound } from 'lucide-vue-next'
import { API_BASE, getAuthToken, request } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import AppButton from '@/components/AppButton.vue'
import QilingLogin from '@/features/auth/QilingLogin.vue'
import AppPagination from '@/components/AppPagination.vue'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import type { SingleResponse } from '@/types'
interface Row { id:number; username?:string; nickname?:string; user_name?:string; user_id?:number; account_user_id?:number; balance?:string; total_cost?:string; created_at:string; model_name?:string; billing_type?:string; cost?:string; balance_after?:string; status?:number|string; out_trade_no?:string; amount?:string; is_super_admin?:boolean }
interface Table {items:Row[]; pagination:{total:number;page:number;page_size:number;pages:number};summary?:{total_cost:string;total_transactions:number};snapshot_id?:number}
interface Recharge {out_trade_no:string; amount:string; code_url?:string; status:string; expires_at?:string}
const props=defineProps<{section:'profile'|'orders'|'billing'|'users'}>()
const auth=useAuthStore(), route=useRoute()
const titles={profile:'个人账户',orders:'充值订单',billing:'消费账单',users:'用户管理'}
const data=ref<Table>(), loading=ref(false), error=ref(''), page=ref(1), pageSize=ref(20), search=ref(''), status=ref(''), userId=ref(''), start=ref(''), end=ref('')
const parties=ref<{id:number;name:string}[]>([])
const rechargeOpen=ref(false), amount=ref('100'), recharge=ref<Recharge>(), qr=ref(''), paymentBusy=ref(false), paymentError=ref('')
const creditUser=ref<Row>(), creditAmount=ref(''), creditBusy=ref(false)
const bindOpen=ref(false), editOpen=ref(false), nickname=ref(''), profileBusy=ref(false), oldPassword=ref(''), newPassword=ref('')
const total=computed(()=>data.value?.pagination.total??0)
let epoch=0, poll:ReturnType<typeof setTimeout>|undefined, disposed=false
const money=(value:unknown)=>Number(value??0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:6})
const orderLabels:Record<string,string>={pending:'待支付',paid:'已支付',expired:'已过期',closed:'已关闭',failed:'失败',refunding:'退款中',refunded:'已退款',refund_closed:'退款关闭'}
const filters=()=>new URLSearchParams({...(search.value?{search:search.value}:{}),...(status.value?{status:status.value}:{}),...(userId.value?{user_id:userId.value}:{}),...(start.value?{start_date:start.value}:{}),...(end.value?{end_date:end.value}:{})})
async function load(){
  const current=++epoch;loading.value=true;error.value=''
  try {
    if(props.section==='profile'){await auth.refreshMe();return}
    const query=filters();query.set('page',String(page.value));query.set('page_size',String(pageSize.value))
    const path=props.section==='users'?'/users':props.section==='orders'?'/account/orders':auth.isSuperAdmin?'/billing/statements':'/billing/records'
    const result=await request<SingleResponse<Table>>(`${path}?${query}`)
    if(current===epoch)data.value=result.data
    if(props.section==='billing'&&auth.isSuperAdmin&&!parties.value.length) parties.value=(await request<SingleResponse<{users:{id:number;name:string}[]}>>('/billing/statements/parties')).data.users
  } catch(e){if(current===epoch)error.value=e instanceof Error?e.message:'加载失败'}
  finally{if(current===epoch)loading.value=false}
}
function applyFilters(){page.value=1;void load()}
async function checkPayment(){
  clearTimeout(poll)
  if(!recharge.value||!rechargeOpen.value||disposed)return
  try {
    const result=await request<SingleResponse<Recharge>>('/account/recharge/'+recharge.value.out_trade_no)
    if(disposed)return
    recharge.value=result.data
    if(result.data.status==='paid'){notice.success('充值成功，余额已到账');await auth.refreshMe();rechargeOpen.value=false;return}
    if(result.data.status==='pending')poll=setTimeout(checkPayment,3000)
  } catch(e){paymentError.value=e instanceof Error?e.message:'暂时无法查询支付状态'}
}
async function createRecharge(){
  paymentBusy.value=true;paymentError.value=''
  try {
    recharge.value=(await request<SingleResponse<Recharge>>('/account/recharge',{method:'POST',body:JSON.stringify({amount:amount.value})})).data
    if(recharge.value.code_url){const QRCode=await import('qrcode');qr.value=await QRCode.toDataURL(recharge.value.code_url,{width:240,margin:2})}
    void checkPayment()
  } catch(e){paymentError.value=e instanceof Error?e.message:'创建订单失败'} finally{paymentBusy.value=false}
}
async function refund(row:Row){
  if(!await appConfirm({title:'确认原路退款？',message:`订单 ${row.out_trade_no}，金额 ¥${money(row.amount)}。退款会扣回用户账户余额。`,confirmLabel:'确认退款'}))return
  try {await request('/account/orders/'+row.out_trade_no+'/refund',{method:'POST',body:JSON.stringify({reason:'管理员退款'})});notice.success('退款请求已提交');await load()}catch(e){notice.error(e instanceof Error?e.message:'退款失败')}
}
async function toggleUser(row:Row){
  if(!await appConfirm({title:row.status===1?'停用此用户？':'启用此用户？',message:'账户余额与历史记录会保留。'}))return
  try {await request('/users/'+row.id,{method:'PATCH',body:JSON.stringify({status:row.status===1?0:1})});await load()}catch(e){notice.error(e instanceof Error?e.message:'操作失败')}
}
async function credit(){
  if(!creditUser.value)return
  creditBusy.value=true
  try {await request('/account/balance/topup',{method:'POST',body:JSON.stringify({account_user_id:creditUser.value.id,amount:creditAmount.value,note:'管理员增额'})});creditUser.value=undefined;creditAmount.value='';notice.success('余额已更新');await load()}catch(e){notice.error(e instanceof Error?e.message:'增额失败')}finally{creditBusy.value=false}
}
async function updateProfile(){
  profileBusy.value=true
  try{await request('/auth/profile',{method:'PATCH',body:JSON.stringify({nickname:nickname.value})});await auth.refreshMe();editOpen.value=false;notice.success('昵称已更新')}catch(e){notice.error(e instanceof Error?e.message:'保存失败')}finally{profileBusy.value=false}
}
async function avatar(event:Event){
  const input=event.target as HTMLInputElement,file=input.files?.[0];if(!file)return
  const form=new FormData();form.append('file',file);profileBusy.value=true
  try{await request('/auth/avatar',{method:'POST',body:form});await auth.refreshMe();notice.success('头像已更新')}catch(e){notice.error(e instanceof Error?e.message:'上传失败')}finally{profileBusy.value=false;input.value=''}
}
async function changePassword(){
  profileBusy.value=true
  try{await request('/auth/change-password',{method:'POST',body:JSON.stringify({old_password:oldPassword.value,new_password:newPassword.value})});oldPassword.value='';newPassword.value='';notice.success('密码已修改')}catch(e){notice.error(e instanceof Error?e.message:'修改失败')}finally{profileBusy.value=false}
}
async function exportCSV(){
  try {
    const query=filters();if(data.value?.snapshot_id!==undefined)query.set('snapshot_id',String(data.value.snapshot_id))
    const response=await fetch(`${API_BASE}/billing/statements/export?${query}`,{headers:{Authorization:'Bearer '+getAuthToken()}})
    if(!response.ok||!response.headers.get('content-type')?.includes('text/csv'))throw new Error('导出失败，请重试')
    const url=URL.createObjectURL(await response.blob()), a=document.createElement('a');a.href=url;a.download='billing-statement.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
  }catch(e){notice.error(e instanceof Error?e.message:'导出失败')}
}
watch(()=>props.section,()=>{page.value=1;search.value='';status.value='';userId.value='';data.value=undefined;void load()},{immediate:true})
watch(rechargeOpen,open=>{if(!open){clearTimeout(poll);recharge.value=undefined;qr.value='';paymentError.value=''}})
watch(()=>route.query.recharge,value=>{if(value==='1')rechargeOpen.value=true},{immediate:true})
onBeforeUnmount(()=>{disposed=true;++epoch;clearTimeout(poll)})
</script>
<template>
<main class="account-page">
  <header class="account-header"><div><span class="eyebrow">CAT API / ACCOUNT</span><h1>{{titles[section]}}</h1><p class="muted">{{section==='users'?'管理用户状态、余额和使用情况。':section==='orders'?'查看账户充值与退款状态。':section==='billing'?'每一笔模型调用，都有迹可循。':'余额、用量与账户信息，尽在此处。'}}</p></div><AppButton variant="secondary" :loading="loading" @click="load"><RefreshCw :size="16"/>刷新</AppButton></header>
  <p v-if="error" class="account-error" role="alert">{{error}} <button @click="load">重试</button></p>
  <template v-if="section==='profile'">
    <div class="account-cards"><section class="account-card"><Wallet class="accent" :size="26"/><p class="muted">可用余额</p><strong class="account-value">¥ {{money(auth.balance)}}</strong><AppButton @click="rechargeOpen=true">充值<ArrowUpRight :size="16"/></AppButton></section><section class="account-card"><p class="muted">累计消费</p><strong class="account-value">¥ {{money(auth.totalCost)}}</strong><RouterLink to="/billing">查看消费账单 →</RouterLink></section></div>
    <section class="account-card identity-card"><img v-if="auth.user?.avatar_url" :src="auth.user.avatar_url" alt="当前用户头像" width="52" height="52" style="border-radius:14px;object-fit:cover"><UserRound v-else :size="28"/><div><h2>{{auth.user?.nickname || auth.user?.username}}</h2><p class="muted">用户编号 {{auth.user?.id}} <span v-if="auth.isSuperAdmin"> · 超级管理员</span></p></div><AppButton variant="secondary" @click="nickname=auth.user?.nickname||auth.user?.username||'';editOpen=true">编辑昵称</AppButton><label>更换头像<input type="file" accept="image/png,image/jpeg,image/webp" :disabled="profileBusy" @change="avatar"></label><RouterLink to="/platform/keys">管理 API Key →</RouterLink></section>
    <section v-if="auth.provider==='qiling'&&!auth.qilingBound" class="account-card" style="margin-top:24px"><h2>绑定器灵账号</h2><p class="muted">绑定后可使用器灵扫码登录此账户，保留现有余额和记录。</p><AppButton @click="bindOpen=true">绑定器灵</AppButton></section>
    <section v-if="auth.provider==='password'" class="account-card" style="margin-top:24px"><h2>修改密码</h2><form class="account-filters" @submit.prevent="changePassword"><label>当前密码<input v-model="oldPassword" type="password" autocomplete="current-password" required></label><label>新密码<input v-model="newPassword" type="password" autocomplete="new-password" minlength="8" required></label><AppButton type="submit" :loading="profileBusy">修改密码</AppButton></form></section>
    <p class="muted" style="margin-top:24px"><a href="/api/auth/legal/terms" target="_blank" rel="noopener">用户协议</a> · <a href="/api/auth/legal/privacy" target="_blank" rel="noopener">隐私政策</a> · <a href="/api/auth/legal/privacy#account-data-requests" target="_blank" rel="noopener">账号与数据申请</a></p>
  </template>
  <section v-else class="account-card account-ledger" :aria-busy="loading">
    <form class="account-filters" @submit.prevent="applyFilters">
      <label v-if="section!=='billing'">搜索<input v-model="search" :placeholder="section==='users'?'用户名或昵称':'订单号或用户'"></label>
      <template v-if="section==='billing'&&auth.isSuperAdmin"><label>操作用户<select v-model="userId"><option value="">全部用户</option><option v-for="item in parties" :key="item.id" :value="item.id">{{item.name}} · {{item.id}}</option></select></label><label>开始日期<input v-model="start" type="date"></label><label>结束日期<input v-model="end" type="date"></label></template>
      <label v-if="section==='orders'">订单状态<select v-model="status"><option value="">全部状态</option><option v-for="(label,key) in orderLabels" :key="key" :value="key">{{label}}</option></select></label>
      <AppButton type="submit" variant="secondary" :disabled="loading">查询</AppButton><AppButton v-if="section==='billing'&&auth.isSuperAdmin" variant="secondary" @click="exportCSV">导出账单</AppButton>
    </form>
    <p v-if="data?.summary" class="muted">实际消费 ¥ {{money(data.summary.total_cost)}} · {{data.summary.total_transactions}} 笔</p>
    <div class="account-table-scroll"><table><thead><tr v-if="section==='users'"><th>用户</th><th>状态</th><th>余额</th><th>累计消费</th><th>操作</th></tr><tr v-else-if="section==='orders'"><th>订单号</th><th>用户</th><th>金额</th><th>状态</th><th>时间</th><th>操作</th></tr><tr v-else><th>流水编号</th><th>操作用户</th><th>类别</th><th>金额</th><th>扣后余额</th><th>时间</th></tr></thead>
    <tbody><template v-for="row in data?.items" :key="row.id"><tr v-if="section==='users'"><td><strong>{{row.nickname||row.username}}</strong><small>#{{row.id}} · {{row.username}}</small></td><td><span class="account-badge">{{row.status===1?'正常':'已停用'}}</span></td><td>¥ {{money(row.balance)}}</td><td>¥ {{money(row.total_cost)}}</td><td><AppButton size="sm" variant="secondary" @click="creditUser=row">增额</AppButton><AppButton v-if="!row.is_super_admin" size="sm" variant="ghost" @click="toggleUser(row)">{{row.status===1?'停用':'启用'}}</AppButton></td></tr>
    <tr v-else-if="section==='orders'"><td>{{row.out_trade_no}}</td><td>{{row.nickname||row.username||row.user_id}}</td><td>¥ {{money(row.amount)}}</td><td><span class="account-badge">{{orderLabels[String(row.status)]||row.status}}</span></td><td>{{row.created_at}}</td><td><AppButton v-if="auth.isSuperAdmin&&['paid','refunding'].includes(String(row.status))" variant="ghost" size="sm" @click="refund(row)">{{row.status==='refunding'?'查询退款':'退款'}}</AppButton></td></tr>
    <tr v-else><td>#{{row.id}}</td><td>{{row.user_name||row.user_id||'历史记录'}}</td><td>{{row.billing_type==='text'?'文本':row.billing_type==='image'?'图片':row.billing_type==='video'?'视频':row.billing_type}}</td><td>¥ {{money(row.cost)}}</td><td>{{row.balance_after==null?'—':'¥ '+money(row.balance_after)}}</td><td>{{row.created_at}}</td></tr></template></tbody></table></div>
    <div v-if="!data?.items.length" class="account-empty">{{loading?'正在加载…':'暂无记录'}}</div><AppPagination :page="page" :page-size="pageSize" :total="total" @page-change="next=>{page=next;load()}" @size-change="size=>{pageSize=size;applyFilters()}"/>
  </section>
  <ElDialog class="console-dialog" v-model="bindOpen" title="绑定器灵账号" width="min(440px, calc(100vw - 32px))" align-center append-to-body destroy-on-close><div class="payment-dialog"><QilingLogin bind @bound="auth.refreshMe();bindOpen=false"/></div></ElDialog>
  <ElDialog class="console-dialog" v-model="editOpen" title="编辑昵称" width="min(440px, calc(100vw - 32px))" align-center append-to-body :close-on-click-modal="!profileBusy" :show-close="!profileBusy"><form class="payment-dialog" @submit.prevent="updateProfile"><label>昵称<input v-model="nickname" maxlength="100" required></label><AppButton type="submit" :loading="profileBusy">保存</AppButton></form></ElDialog>
  <ElDialog class="console-dialog" v-model="rechargeOpen" title="账户充值" width="min(440px, calc(100vw - 32px))" align-center append-to-body :close-on-click-modal="!paymentBusy" :close-on-press-escape="!paymentBusy" :show-close="!paymentBusy">
    <div class="payment-dialog"><template v-if="!recharge"><p class="muted">充值金额将计入你在 Cat API 的账户余额。</p><form @submit.prevent="createRecharge"><label>充值金额（元）<input v-model="amount" type="number" min="0.01" max="999999" step="0.01" required></label><AppButton type="submit" :loading="paymentBusy">生成微信支付码</AppButton></form></template><template v-else><strong class="account-value">¥ {{money(recharge.amount)}}</strong><img v-if="qr" :src="qr" width="240" height="240" alt="微信支付二维码"><p>请使用微信扫码支付</p><p class="muted">{{orderLabels[recharge.status]||recharge.status}} · {{recharge.out_trade_no}}</p><AppButton variant="secondary" @click="checkPayment">我已支付，查询状态</AppButton></template><p v-if="paymentError" role="alert" class="account-error">{{paymentError}}</p></div>
  </ElDialog>
  <ElDialog class="console-dialog" :model-value="Boolean(creditUser)" title="管理员增额" width="min(440px, calc(100vw - 32px))" align-center append-to-body :close-on-click-modal="!creditBusy" :close-on-press-escape="!creditBusy" :show-close="!creditBusy" @update:model-value="open=>{if(!open&&!creditBusy)creditUser=undefined}"><form class="payment-dialog" @submit.prevent="credit"><p>用户：{{creditUser?.nickname||creditUser?.username}}（#{{creditUser?.id}}）</p><label>增额金额（元）<input v-model="creditAmount" type="number" min="0.01" step="0.01" required></label><AppButton type="submit" :loading="creditBusy">确认增额</AppButton></form></ElDialog>
</main>
</template>
