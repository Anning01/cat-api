<script setup lang="ts">
import { useId, computed, onBeforeUnmount, ref, watch } from 'vue'
import AppDialog from '@/components/AppDialog.vue'
import { RefreshCw, Plus, SlidersHorizontal } from 'lucide-vue-next'
import ConsolePage from '@/components/ConsolePage.vue'
import ConsoleTable from '@/components/ConsoleTable.vue'
import AppButton from '@/components/AppButton.vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppStatusBadge from '@/components/AppStatusBadge.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppActionMenu from '@/components/AppActionMenu.vue'
import { request } from '@/api'
import { tr } from '@/i18n'
import { useAuthStore } from '@/features/auth/authStore'
import { money, dateTime, label, orderLabels, orderTone, billingLabels } from '@/shared/console'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import type { AccountRow, AccountTable } from '@/features/account/types'
import type { SingleResponse } from '@/types'

const auth = useAuthStore()
const data = ref<AccountTable>(), stats = ref<{user_count: number; balance_total: string; user_total_cost: number}>()
const page = ref(1), pageSize = ref(20), search = ref(''), status = ref(''), role = ref(''), balanceView = ref(''), orderBy = ref('-id')
const loading = ref(false), error = ref(''), compact = ref(false)
const columns = ref({ role: true, status: true, created: true })
const selectedId = ref<number>(), detail = ref<AccountRow>(), detailData = ref<AccountTable>(), detailTab = ref('profile'), detailPage = ref(1), detailBusy = ref(false), detailError = ref('')
const creditUser = ref<AccountRow>(), creditAmount = ref(''), creditNote = ref(''), creditBusy = ref(false), creditError = ref('')
const createOpen = ref(false), username = ref(''), nickname = ref(''), password = ref(''), createBusy = ref(false), createError = ref('')
let epoch = 0, detailEpoch = 0
const tabs = [{id:'profile',label:'基本资料'},{id:'transactions',label:'余额流水'},{id:'billing',label:'消费记录'},{id:'orders',label:'充值订单'},{id:'events',label:'操作记录'}]
const actions: Record<string,string> = { create:'创建用户', enable:'启用账户', disable:'停用账户', close:'注销访问', topup:'管理员增额' }
const transactionLabels: Record<string,string> = { topup:'入账', consume:'消费', adjust:'调整', refund:'退款' }
const previewBalance = computed(() => Number(creditUser.value?.balance || 0) + Number(creditAmount.value || 0))
async function load() {
  const current = ++epoch; loading.value = true; error.value = ''
  const query = new URLSearchParams({ page:String(page.value), page_size:String(pageSize.value), order_by:orderBy.value })
  for (const [key,value] of Object.entries({search:search.value, status:status.value, role:role.value, balance_view:balanceView.value})) if(value) query.set(key,value)
  try {
    const [result, totals] = await Promise.all([request<SingleResponse<AccountTable>>('/users?'+query), request<SingleResponse<NonNullable<typeof stats.value>>>('/users/stats').catch(() => null)])
    if(current === epoch) { data.value = result.data; stats.value = totals?.data }
  } catch(cause) { if(current === epoch) error.value = cause instanceof Error ? cause.message : tr('加载失败') }
  finally { if(current === epoch) loading.value = false }
}
function apply() { page.value = 1; void load() }
function reset() { search.value='';status.value='';role.value='';balanceView.value='';orderBy.value='-id';apply() }
async function loadDetail() {
  const id=selectedId.value, current=++detailEpoch
  detailError.value='';detailData.value=undefined
  if(!id) { detail.value=undefined;return }
  detailBusy.value=true
  const tab=detailTab.value, query='page='+detailPage.value+'&page_size=10'
  const path=tab==='billing'?'/billing/statements?account_user_id='+id+'&'+query:tab==='orders'?'/account/orders?account_user_id='+id+'&'+query:'/users/'+id+'/'+tab+'?'+query
  try {
    const [user, records]=await Promise.all([request<SingleResponse<AccountRow>>('/users/'+id),tab==='profile'?Promise.resolve(null):request<SingleResponse<AccountTable>>(path)])
    if(current===detailEpoch){detail.value=user.data;detailData.value=records?.data}
  }catch(cause){if(current===detailEpoch)detailError.value=cause instanceof Error?cause.message:tr('加载失败')}
  finally{if(current===detailEpoch)detailBusy.value=false}
}
function showUser(row:AccountRow){detail.value=row;detailTab.value='profile';detailPage.value=1;selectedId.value=row.id}
watch([selectedId,detailTab,detailPage],loadDetail)
function startCredit(row:AccountRow){creditUser.value=row;creditAmount.value='';creditNote.value='';creditError.value=''}
async function credit(){
  if(!creditUser.value||creditBusy.value)return
  creditBusy.value=true;creditError.value=''
  try{await request('/account/balance/topup',{method:'POST',body:JSON.stringify({account_user_id:creditUser.value.id,amount:creditAmount.value,note:creditNote.value.trim()})});creditUser.value=undefined;notice.success(tr('余额已更新'));await Promise.all([load(),auth.refreshMe()]);if(selectedId.value)await loadDetail()}
  catch(cause){creditError.value=cause instanceof Error?cause.message:tr('增额失败')}
  finally{creditBusy.value=false}
}
async function toggle(row:AccountRow){
  if(row.is_super_admin||row.id===auth.user?.id)return
  if(!await appConfirm({title:tr(row.status===1?'停用此用户？':'启用此用户？'),message:tr('停用后无法登录；余额和历史记录保留。'),confirmLabel:tr(row.status===1?'停用':'启用')}))return
  try{await request('/users/'+row.id,{method:'PATCH',body:JSON.stringify({status:row.status===1?0:1})});notice.success(tr('账户状态已更新'));await load();if(selectedId.value===row.id)await loadDetail()}catch(cause){notice.error(cause instanceof Error?cause.message:tr('操作失败'))}
}
async function create(){
  if(createBusy.value)return
  createBusy.value=true;createError.value=''
  try{await request('/users',{method:'POST',body:JSON.stringify({username:username.value.trim(),nickname:nickname.value.trim(),password:password.value})});createOpen.value=false;password.value='';username.value='';nickname.value='';notice.success(tr('用户已创建'));apply()}
  catch(cause){createError.value=cause instanceof Error?cause.message:tr('创建失败')}
  finally{createBusy.value=false}
}
onBeforeUnmount(()=>{++epoch;++detailEpoch})
void load()
const formId=useId()
const createDialog=ref<InstanceType<typeof AppDialog>>()
const creditDialog=ref<InstanceType<typeof AppDialog>>()
</script>
<template>
  <ConsolePage :title="tr('用户管理')" :description="tr('管理用户账户、余额与使用情况。')">
    <template #actions><AppButton variant="secondary" :loading="loading" @click="load"><RefreshCw :size="16"/>{{ tr('刷新') }}</AppButton><AppButton v-if="auth.provider==='password'" variant="primary" @click="createOpen=true"><Plus :size="16"/>{{ tr('创建用户') }}</AppButton></template>
    <div class="console-summary" :aria-label="tr('全平台')"><div><span>{{ tr('用户总数') }}</span><strong>{{ stats?.user_count ?? '—' }}</strong></div><div><span>{{ tr('用户余额合计') }}</span><strong>{{ stats?.balance_total != null ? '¥ '+money(stats.balance_total) : '—' }}</strong></div><div><span>{{ tr('累计实际消费') }}</span><strong>{{ stats?.user_total_cost != null ? '¥ '+money(stats.user_total_cost) : '—' }}</strong></div></div>
    <div class="console-tabs" role="group" :aria-label="tr('用户视图')"><button v-for="view in [{value:'',label:'全部用户'},{value:'low',label:'余额预警'},{value:'negative',label:'欠费账户'}]" :key="view.value" :class="{'is-active':balanceView===view.value}" :aria-pressed="balanceView===view.value" @click="balanceView=view.value;apply()">{{ tr(view.label) }}</button></div>
    <search><form class="console-filterbar" @submit.prevent="apply"><label :for="formId+'-field-1'">{{ tr('用户名 / 昵称 / ID') }}<input name="field-1" :id="formId+'-field-1'" v-model="search" type="search" autocorrect="off" :placeholder="tr('搜索用户')" maxlength="100" /></label><label :for="formId+'-field-2'">{{ tr('状态') }}<select name="field-2" :id="formId+'-field-2'" v-model="status"><option value="">{{ tr('全部') }}</option><option value="1">{{ tr('正常') }}</option><option value="0">{{ tr('已停用') }}</option></select></label><label :for="formId+'-field-3'">{{ tr('身份') }}<select name="field-3" :id="formId+'-field-3'" v-model="role"><option value="">{{ tr('全部') }}</option><option value="user">{{ tr('普通用户') }}</option><option value="admin">{{ tr('超级管理员') }}</option></select></label><AppButton type="submit" variant="primary" :disabled="loading">{{ tr('查询') }}</AppButton><AppButton variant="secondary" @click="reset">{{ tr('重置') }}</AppButton></form></search>
    <p v-if="balanceView==='low'" class="muted">{{ tr('余额预警：可用余额不高于 ¥10，包含尚未充值的账户。') }}</p>
    <p v-if="error" role="alert" class="console-error">{{ error }} <button @click="load">{{ tr('重试') }}</button></p>
    <section class="console-table-panel" :aria-busy="loading" :class="{'is-compact':compact}">
      <div class="console-table-toolbar"><h2>{{ tr('用户列表') }} <small>{{ tr('共 {p0} 位用户',{p0:data?.pagination.total??'—'}) }}</small></h2><div class="console-inline"><select v-model="orderBy" :aria-label="tr('排序')" @change="apply"><option value="-id">{{ tr('最新创建优先') }}</option><option value="id">{{ tr('最早创建优先') }}</option></select><details class="table-column-settings"><summary><SlidersHorizontal :size="15"/>{{ tr('列设置') }}</summary><div><label :for="formId+'-column-'+field.key" v-for="field in [{key:'role' as const,label:'身份'},{key:'status' as const,label:'状态'},{key:'created' as const,label:'创建时间'}]" :key="field.key"><input name="field-4" :id="formId+'-column-'+field.key" v-model="columns[field.key]" type="checkbox"/>{{ tr(field.label) }}</label></div></details><label :for="formId+'-field-5'" class="console-check"><input name="field-5" :id="formId+'-field-5'" v-model="compact" type="checkbox"/>{{ tr('紧凑') }}</label></div></div>
      <ConsoleTable :caption="tr('用户列表')"><thead><tr><th scope="col">{{ tr('用户') }}</th><th scope="col" v-if="columns.role">{{ tr('身份') }}</th><th scope="col" v-if="columns.status">{{ tr('状态') }}</th><th scope="col" class="numeric">{{ tr('可用余额') }}</th><th scope="col" class="numeric">{{ tr('累计消费') }}</th><th scope="col" v-if="columns.created">{{ tr('创建时间') }}</th><th scope="col" class="row-actions">{{ tr('操作') }}</th></tr></thead><tbody><tr v-for="row in data?.items" :key="row.id" :class="{'is-selected':selectedId===row.id}"><th scope="row"><button class="user-cell" @click="showUser(row)"><AppAvatar :name="row.nickname||row.username"/><span><strong>{{ row.nickname||row.username }}</strong><small>{{ row.username }} · #{{ row.id }}</small></span></button></th><td v-if="columns.role">{{ tr(row.is_super_admin?'超级管理员':'普通用户') }}</td><td v-if="columns.status"><AppStatusBadge :tone="row.status===1?'success':'neutral'">{{ tr(row.status===1?'正常':'已停用') }}</AppStatusBadge></td><td class="numeric" :class="{'text-danger':Number(row.balance)<0}">¥ {{ money(row.balance) }} <AppStatusBadge v-if="Number(row.balance)>=0&&Number(row.balance)<=10" tone="warning">{{ tr('低余额') }}</AppStatusBadge></td><td class="numeric">¥ {{ money(row.total_cost) }}</td><td v-if="columns.created" class="date-cell">{{ dateTime(row.created_at) }}</td><td class="row-actions"><AppButton size="sm" @click="showUser(row)">{{ tr('详情') }}</AppButton><AppButton size="sm" @click="startCredit(row)">{{ tr('增额') }}</AppButton><AppActionMenu v-if="!row.is_super_admin&&row.id!==auth.user?.id" :items="[{value:'status',label:row.status===1?'停用':'启用',danger:row.status===1}]" @select="toggle(row)"/></td></tr></tbody></ConsoleTable>
      <div v-if="loading&&!data" class="console-skeleton" role="status">{{ tr('正在加载…') }}<i v-for="n in 5" :key="n"/></div><div v-else-if="!data?.items.length&&!error" class="console-empty"><h3>{{ tr(search||status||role||balanceView?'未找到符合条件的用户':'还没有用户') }}</h3><p>{{ tr('可以调整筛选条件，或等待用户完成登录。') }}</p><AppButton variant="secondary" @click="reset">{{ tr('清空筛选') }}</AppButton></div>
      <AppPagination :page="page" :page-size="pageSize" :total="data?.pagination.total??0" @page-change="value=>{page=value;load()}" @size-change="value=>{pageSize=value;apply()}"/>
    </section>
    <AppDialog drawer class="console-drawer" :model-value="Boolean(selectedId)" :title="tr('用户详情')" size="min(760px, 100vw)" @update:model-value="value=>{if(!value)selectedId=undefined}">
      <template v-if="detail"><div class="user-detail-identity"><AppAvatar :name="detail.nickname||detail.username" :src="detail.avatar_url" :size="44"/><div><h2>{{ detail.nickname||detail.username }}</h2><p class="muted">{{ detail.username }} · #{{ detail.id }}</p></div><AppStatusBadge :tone="detail.status===1?'success':'neutral'">{{ tr(detail.status===1?'正常':'已停用') }}</AppStatusBadge></div><div class="console-summary"><div><span>{{ tr('可用余额') }}</span><strong>¥ {{ money(detail.balance) }}</strong></div><div><span>{{ tr('累计消费') }}</span><strong>¥ {{ money(detail.total_cost) }}</strong></div></div><div class="console-tabs" role="group" :aria-label="tr('用户详情')"><button v-for="tab in tabs" :key="tab.id" :aria-pressed="detailTab===tab.id" :class="{'is-active':detailTab===tab.id}" @click="detailPage=1;detailTab=tab.id">{{ tr(tab.label) }}</button></div></template>
      <p v-if="detailError" class="console-error" role="alert">{{ detailError }} <button @click="loadDetail">{{ tr('重试') }}</button></p>
      <div v-if="detailBusy" role="status" class="console-skeleton">{{ tr('正在加载…') }}<i v-for="n in 3" :key="n"/></div>
      <template v-else-if="detail&&!detailError"><dl v-if="detailTab==='profile'" class="detail-fields"><div><dt>{{ tr('用户名') }}</dt><dd>{{ detail.username }}</dd></div><div><dt>{{ tr('用户编号') }}</dt><dd>#{{ detail.id }}</dd></div><div><dt>{{ tr('身份') }}</dt><dd>{{ tr(detail.is_super_admin?'超级管理员':'普通用户') }}</dd></div><div><dt>{{ tr('创建时间') }}</dt><dd>{{ dateTime(detail.created_at) }}</dd></div><div><dt>{{ tr('最近会话活动') }}</dt><dd>{{ dateTime(detail.last_seen_at) }}</dd></div><div><dt>{{ tr('器灵账号') }}</dt><dd>{{ tr(detail.qiling_bound?'已绑定':'未绑定') }}</dd></div><div><dt>{{ tr('有效 API Keys') }}</dt><dd>{{ detail.active_key_count??'—' }}</dd></div></dl>
      <template v-else><p v-if="detailTab==='events'" class="muted">{{ tr('记录此版本启用后的账户管理操作，不包含历史补录。') }}</p><ConsoleTable :caption="tr(tabs.find(tab=>tab.id===detailTab)?.label||'用户详情')"><thead><tr><th scope="col">{{ tr('时间') }}</th><th scope="col">{{ tr(detailTab==='orders'?'订单号':detailTab==='events'?'操作':'类别') }}</th><th scope="col">{{ tr(detailTab==='events'?'操作人':detailTab==='orders'?'金额':'变动金额') }}</th><th scope="col">{{ tr(detailTab==='orders'?'状态':detailTab==='events'?'备注':'扣后余额') }}</th></tr></thead><tbody><tr v-for="row in detailData?.items" :key="row.id"><td>{{ dateTime(row.created_at) }}</td><td>{{ detailTab==='orders'?row.out_trade_no:detailTab==='events'?label(row.action,actions):detailTab==='transactions'?label(row.type,transactionLabels):label(row.billing_type,billingLabels) }}</td><td>{{ detailTab==='events'?row.operator_name:'¥ '+money(detailTab==='orders'?row.amount:detailTab==='transactions'?row.change_amount:row.cost) }}</td><td><AppStatusBadge v-if="detailTab==='orders'" :tone="orderTone(String(row.status))">{{ label(String(row.status),orderLabels) }}</AppStatusBadge><span v-else>{{ detailTab==='events'?row.note||'—':row.balance_after==null?'—':'¥ '+money(row.balance_after) }}</span><small v-if="detailTab==='transactions'">{{ row.note }} <span v-if="row.operator_user_id"> · {{ tr('操作人') }} #{{ row.operator_user_id }}</span></small></td></tr></tbody></ConsoleTable><p v-if="!detailData?.items.length" class="console-empty">{{ tr('暂无记录') }}</p><AppPagination :page="detailPage" :page-size="10" :page-size-options="[10]" :total="detailData?.pagination.total??0" @page-change="value=>detailPage=value"/></template></template>
      <template #footer><AppButton variant="secondary" @click="selectedId=undefined">{{ tr('关闭') }}</AppButton><AppButton v-if="detail" variant="primary" @click="startCredit(detail)">{{ tr('管理员增额') }}</AppButton></template>
    </AppDialog>
    <AppDialog ref="creditDialog" class="console-dialog" :model-value="Boolean(creditUser)" :title="tr('管理员增额')" guard-changes width="480px" :show-close="!creditBusy" :close-on-click-modal="!creditBusy" :close-on-press-escape="!creditBusy" @update:model-value="value=>{if(!value&&!creditBusy)creditUser=undefined}"><form class="console-form" @submit.prevent="credit"><p>{{ creditUser?.nickname||creditUser?.username }} · #{{ creditUser?.id }}</p><label :for="formId+'-field-6'">{{ tr('增额金额（元）') }}<input name="field-6" :id="formId+'-field-6'" v-model="creditAmount" autofocus type="number" min="0.01" step="0.01" max="999999" required/></label><label :for="formId+'-field-7'">{{ tr('原因 / 备注') }}<textarea name="field-7" :id="formId+'-field-7'" v-model="creditNote" maxlength="255" required rows="3"/></label><p class="muted">{{ tr('当前余额') }} ¥ {{ money(creditUser?.balance) }} → {{ tr('预计余额') }} ¥ {{ money(previewBalance) }}</p><p v-if="creditError" role="alert" class="console-error">{{ creditError }}</p><footer><AppButton variant="secondary" :disabled="creditBusy" @click="creditDialog?.requestClose()">{{ tr('取消') }}</AppButton><AppButton type="submit" variant="primary" :loading="creditBusy">{{ tr('确认增额') }}</AppButton></footer></form></AppDialog>
    <AppDialog ref="createDialog" v-model="createOpen" class="console-dialog" :title="tr('创建用户')" guard-changes width="480px" :show-close="!createBusy" :close-on-click-modal="!createBusy" :close-on-press-escape="!createBusy" @closed="password='' "><form class="console-form" @submit.prevent="create"><label :for="formId+'-field-8'">{{ tr('用户名') }}<input name="field-8" :id="formId+'-field-8'" v-model="username" autofocus autocorrect="off" autocapitalize="none" :spellcheck="false" required maxlength="100" autocomplete="off"/></label><label :for="formId+'-field-9'">{{ tr('昵称') }}<input name="field-9" :id="formId+'-field-9'" v-model="nickname" maxlength="100"/></label><label :for="formId+'-field-10'">{{ tr('初始密码') }}<input name="field-10" :id="formId+'-field-10'" v-model="password" type="password" minlength="8" maxlength="200" autocomplete="new-password" required/></label><p class="muted">{{ tr('创建普通用户，不授予管理员权限。') }}</p><p v-if="createError" role="alert" class="console-error">{{ createError }}</p><footer><AppButton variant="secondary" :disabled="createBusy" @click="createDialog?.requestClose()">{{ tr('取消') }}</AppButton><AppButton type="submit" variant="primary" :loading="createBusy">{{ tr('创建用户') }}</AppButton></footer></form></AppDialog>
  </ConsolePage>
</template>
