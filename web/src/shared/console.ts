import { ref } from 'vue'
import { dateLocale, tr } from '@/i18n'

export const rechargeOpen = ref(false)
export function money(value: unknown, maximumFractionDigits = 6) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? new Intl.NumberFormat(dateLocale.value, { minimumFractionDigits: 2, maximumFractionDigits }).format(number) : '—'
}
export function dateTime(value?: string | null) {
  if (!value) return '—'
  // API timestamps without an offset use the configured platform timezone (Shanghai).
  const normalized = value.replace(' ', 'T')
  const date = new Date(/[zZ]$|[+-]\d\d:\d\d$/.test(normalized) ? normalized : normalized + '+08:00')
  return Number.isNaN(date.valueOf()) ? '—' : new Intl.DateTimeFormat(dateLocale.value, {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date)
}
export const orderLabels: Record<string, string> = { pending: '待支付', paid: '已支付', expired: '已过期', closed: '已关闭', failed: '失败', refunding: '退款中', refunded: '已退款', refund_closed: '退款关闭' }
export const billingLabels: Record<string, string> = { text: '文本', image: '图片', video: '视频', media_processing: '画质增强', asr: '语音识别' }
export function orderTone(status: string): 'success' | 'warning' | 'danger' | 'neutral' {
  return status === 'paid' ? 'success' : ['pending', 'refunding'].includes(status) ? 'warning' : status === 'failed' ? 'danger' : 'neutral'
}
export function label(value: string | undefined, labels: Record<string, string>) { return value ? tr(labels[value] || value) : '—' }
