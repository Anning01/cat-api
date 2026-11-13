<script setup lang="ts">
import { useId, computed, onBeforeUnmount, ref, watch } from 'vue'
import AppDialog from '@/components/AppDialog.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { request } from '@/api'
import { tr } from '@/i18n'
import { money, dateTime, orderLabels, orderTone, label } from '@/shared/console'
import { notice } from '@/shared/notice'
import AppButton from '@/components/AppButton.vue'
import AppStatusBadge from '@/components/AppStatusBadge.vue'
import type { SingleResponse } from '@/types'

const open = defineModel<boolean>({ required: true })
const auth = useAuthStore()
interface Order { out_trade_no: string; amount: string; code_url?: string; status: string; expires_at?: string }
const amount = ref('100'), order = ref<Order>(), qr = ref(''), creating = ref(false), checking = ref(false), error = ref('')
let poll: ReturnType<typeof setTimeout> | undefined, revision = 0
const pending = computed(() => order.value?.status === 'pending')
const expired = computed(() => order.value && ['expired', 'closed', 'failed'].includes(order.value.status))
function reset() { ++revision; clearTimeout(poll); order.value = undefined; qr.value = ''; error.value = ''; creating.value = false; checking.value = false }
watch(open, () => reset())
async function check() {
  clearTimeout(poll)
  if (!open.value || !order.value || checking.value) return
  const current = revision
  checking.value = true
  try {
    const { data } = await request<SingleResponse<Order>>('/account/recharge/' + encodeURIComponent(order.value.out_trade_no))
    if (current !== revision || !open.value) return
    order.value = data; error.value = ''
    if (data.status === 'paid') { await auth.refreshMe(); notice.success(tr('充值成功，余额已到账')); }
  } catch (cause) { if (current === revision) error.value = cause instanceof Error ? cause.message : tr('暂时无法查询支付状态') }
  finally {
    if (current === revision) {
      checking.value = false
      if (open.value && pending.value) poll = setTimeout(check, 3000)
    }
  }
}
async function create() {
  if (creating.value) return
  const current = ++revision
  creating.value = true; error.value = ''
  try {
    const { data } = await request<SingleResponse<Order>>('/account/recharge', { method: 'POST', body: JSON.stringify({ amount: amount.value }) })
    if (current !== revision || !open.value) return
    order.value = data
    if (data.code_url) { const QRCode = await import('qrcode'); const image = await QRCode.toDataURL(data.code_url, { width: 240, margin: 2 }); if (current === revision) qr.value = image }
    if (current === revision) void check()
  } catch (cause) { if (current === revision) error.value = cause instanceof Error ? cause.message : tr('创建订单失败') }
  finally { if (current === revision) creating.value = false }
}
onBeforeUnmount(reset)
const formId=useId()
</script>
<template>
  <AppDialog v-model="open" class="console-dialog" :title="tr('账户充值')" width="480px" :close-on-click-modal="!creating" :close-on-press-escape="!creating" :show-close="!creating">
    <div class="recharge-dialog">
      <p class="muted">{{ auth.user?.nickname || auth.user?.username }} · {{ tr('可用余额') }} ¥ {{ money(auth.balance) }}</p>
      <form v-if="!order" @submit.prevent="create">
        <label :for="formId+'-field-1'" class="console-field">{{ tr('充值金额（元）') }}<input name="field-1" :id="formId+'-field-1'" v-model="amount" autofocus type="number" min="0.01" max="999999" step="0.01" required inputmode="decimal" /></label>
        <div class="recharge-presets"><AppButton v-for="value in [50, 100, 200, 500]" :key="value" variant="secondary" :active="amount === String(value)" @click="amount = String(value)">¥{{ value }}</AppButton></div>
        <p class="muted">{{ tr('充值金额将计入你在 Cat API 的账户余额。') }}</p>
        <AppButton type="submit" variant="primary" block :loading="creating">{{ tr('生成微信支付码') }}</AppButton>
      </form>
      <template v-else>
        <div class="recharge-amount">¥ {{ money(order.amount, 2) }}</div>
        <AppStatusBadge :tone="orderTone(order.status)">{{ label(order.status, orderLabels) }}</AppStatusBadge>
        <img v-if="qr && pending" class="payment-qr" :src="qr" width="240" height="240" :alt="tr('微信支付二维码')" />
        <p v-if="pending">{{ tr('请使用微信扫码支付') }}</p>
        <p v-if="pending && !qr" class="muted">{{ tr('支付二维码暂不可用，请稍后重新查询。') }}</p>
        <dl class="detail-fields"><div><dt>{{ tr('订单号') }}</dt><dd>{{ order.out_trade_no }}</dd></div><div v-if="pending"><dt>{{ tr('有效期至') }}</dt><dd>{{ dateTime(order.expires_at) }}</dd></div></dl>
        <AppButton v-if="pending" variant="secondary" :loading="checking" @click="check">{{ tr('我已支付，查询状态') }}</AppButton>
        <AppButton v-else-if="expired" variant="primary" @click="reset">{{ tr('重新充值') }}</AppButton>
        <AppButton v-else-if="order.status === 'paid'" variant="primary" @click="open = false">{{ tr('完成') }}</AppButton>
        <RouterLink to="/orders" @click="open = false">{{ tr('查看充值订单') }}</RouterLink>
        <p v-if="pending" class="muted">{{ tr('关闭窗口不会取消已创建的订单。') }}</p>
      </template>
      <p v-if="error" role="alert" class="console-error">{{ error }}</p>
    </div>
  </AppDialog>
</template>
