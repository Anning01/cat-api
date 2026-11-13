import { tr } from '@/i18n'
import type { ModelPricing } from '@/types'

interface PricedModel { kinds: readonly string[]; pricing: ModelPricing }
export interface ModelPriceRow { label: string; value: number; unit: string; reference?: boolean }

export function getModelDiscount(model: PricedModel): number {
  const value = model.pricing?.discount
  return typeof value === 'number' && value > 0 ? value : 1
}

export function getDiscountRate(discount: number | undefined | null): string {
  return discount == null ? '' : String(Number((discount * 10).toFixed(1)))
}

const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })
function compareTiers(left: string, right: string) {
  const size = (value: string) => Number.parseFloat(value) * (/k$/i.test(value) ? 1000 : 1)
  return size(left) - size(right) || collator.compare(left, right)
}

export function pixelTierLabel(tier: string): string {
  const labels: Record<string, string> = {
    low: '≤ 2.61 MP', high_capped: '2.61 MP < P ≤ 4.63 MP',
    single_low: tr('单图生成') + ' · ≤ 2.61 MP', single_high: tr('单图生成') + ' · > 2.61 MP',
    layer_low: tr('图层拆分') + ' · ≤ 2.61 MP', layer_high: tr('图层拆分') + ' · > 2.61 MP',
  }
  return labels[tier] ?? tier
}

export function pricingRows(model: PricedModel): ModelPriceRow[] {
  const pricing = model.pricing
  const rows: ModelPriceRow[] = []
  const unit = model.kinds.includes('image') ? tr('张') : pricing.billing_unit === 'second' ? tr('秒')
    : pricing.billing_unit === 'minute' ? tr('分钟') : tr('百万 token')
  for (const [field, label] of [
    ['input_price_per_1m', tr('输入单价')], ['output_price_per_1m', tr('输出单价')], ['cache_input_price_per_1m', tr('缓存输入')],
  ] as const) {
    const value = pricing[field]
    if (value != null) rows.push({ label, value, unit: tr('百万 token') })
  }
  const outputPrices = Object.entries(pricing.prices ?? {})
  if (pricing.billing_unit !== 'pixel_tier') outputPrices.sort(([a], [b]) => compareTiers(a, b))
  for (const [label, value] of outputPrices) {
    rows.push({ label: pricing.billing_unit === 'pixel_tier' ? pixelTierLabel(label) : label, value, unit })
  }
  if (pricing.price_per_minute != null) rows.push({ label: tr('标准单价'), value: pricing.price_per_minute, unit: tr('分钟') })
  for (const tier of pricing.tiers ?? []) rows.push({ label: `≤${tier.short_side_max}p · ≤${tier.fps_max}fps`, value: tier.price, unit: tr('分钟') })
  for (const [tier, value] of Object.entries(pricing.video_reference_prices ?? {}).sort(([a], [b]) => compareTiers(a, b))) {
    rows.push({ label: `${tr(pricing.billing_unit === 'second' ? '输入参考视频' : '含参考视频')} · ${tier}`, value, unit, reference: true })
  }
  return rows
}
