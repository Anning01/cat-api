<script lang="ts">
import type { ModelPricing } from '@/types'

export interface CatalogModel {
  id: string
  name: string
  kinds: string[]
  image_model_type?: string
  video_model_type?: string
  reference_image_urls?: boolean
  tool_calls?: boolean
  json_output?: boolean
  pricing: ModelPricing
}
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ArrowRight,
  Braces,
  Check,
  ChevronDown,
  Copy,
  Film,
  Flame,
  Grid3X3,
  Image,
  LayoutGrid,
  List,
  Monitor,
  RotateCcw,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-vue-next'
import { tr } from '@/i18n'
import { notice } from '@/shared/notice'
import AppSelect from '@/components/AppSelect.vue'

const props = defineProps<{ models: CatalogModel[]; canManage?: boolean; loggedIn?: boolean }>()
const kind = ref('all')
const query = ref('')
const sort = ref('default')
const viewMode = ref<'grid' | 'compact' | 'list'>('list')
const copiedId = ref('')
const selectedSeries = ref<string[]>([])
const selectedResolutions = ref<string[]>([])
const selectedFeatures = ref<string[]>([])

const categoryOrder = ['image', 'video', 'text']
const labels = computed<Record<string, string>>(() => ({
  all: tr('全部'), text: tr('文本'), image: tr('图片'), video: tr('视频'),
  media_processing: tr('画质增强'), asr: tr('语音识别'),
}))
const categories = computed(() => ['all', ...categoryOrder, ...new Set(props.models.flatMap(model => model.kinds))]
  .filter((value, index, values) => values.indexOf(value) === index)
  .filter(value => value === 'all' || props.models.some(model => model.kinds.includes(value))))

const sortOptions = computed(() => [
  { value: 'default', label: tr('按模型排序') },
  { value: 'name', label: tr('名称 A–Z') },
  { value: 'name-desc', label: tr('名称 Z–A') },
  { value: 'newest', label: tr('最近添加') },
])

const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

function getModelSeries(model: CatalogModel): string {
  const combined = `${model.name} ${model.image_model_type ?? ''} ${model.video_model_type ?? ''}`.toLowerCase()
  if (combined.includes('seedance')) return 'Seedance'
  if (combined.includes('seedream')) return 'Seedream'
  if (combined.includes('gpt-image') || (combined.includes('gpt') && model.kinds.includes('image')) || combined.includes('dall-e')) return 'GPT-Image'
  if (combined.includes('gpt')) return 'GPT'
  if (combined.includes('kling')) return 'Kling'
  if (combined.includes('minimax') || combined.includes('hailuo')) return 'MiniMax'
  if (combined.includes('wan') || combined.includes('wanx')) return 'Wan'
  if (combined.includes('deepseek')) return 'DeepSeek'
  if (combined.includes('qwen')) return 'Qwen'
  if (combined.includes('doubao')) return 'Doubao'
  return tr('其他')
}

function getModelResolutions(model: CatalogModel): Set<string> {
  const set = new Set<string>()
  const norm = (s: string) => {
    const l = s.trim().toLowerCase()
    if (l === '4k' || l === '4096' || l === '3840') return '4K'
    if (l.endsWith('p')) return l
    return s
  }
  for (const k of Object.keys(model.pricing.prices ?? {})) {
    set.add(norm(k))
  }
  for (const tier of model.pricing.tiers ?? []) {
    if (tier.short_side_max != null) set.add(`${tier.short_side_max}p`)
  }
  for (const k of Object.keys(model.pricing.video_reference_prices ?? {})) {
    set.add(norm(k))
  }
  return set
}

const seriesOptions = computed(() => {
  const counts: Record<string, number> = {}
  for (const m of props.models) {
    if (kind.value !== 'all' && !m.kinds.includes(kind.value)) continue
    const s = getModelSeries(m)
    counts[s] = (counts[s] ?? 0) + 1
  }
  const preferred = ['Seedance', 'Seedream', 'GPT-Image', 'GPT', 'Kling', 'MiniMax', 'Wan', 'DeepSeek', 'Qwen', 'Doubao']
  const matched = preferred.filter(k => (counts[k] ?? 0) > 0).map(k => ({ key: k, label: k, count: counts[k]! }))
  const otherLabel = tr('其他')
  if ((counts[otherLabel] ?? 0) > 0) {
    matched.push({ key: otherLabel, label: otherLabel, count: counts[otherLabel]! })
  }
  return matched
})

const resolutionOptions = computed(() => {
  const counts: Record<string, number> = {}
  for (const m of props.models) {
    if (kind.value !== 'all' && !m.kinds.includes(kind.value)) continue
    for (const r of getModelResolutions(m)) {
      counts[r] = (counts[r] ?? 0) + 1
    }
  }
  const preferred = ['480p', '720p', '1080p', '4K', '1K', '1.5K', '2K']
  const matched = preferred.filter(k => (counts[k] ?? 0) > 0).map(k => ({ key: k, label: k, count: counts[k]! }))
  for (const [k, count] of Object.entries(counts)) {
    if (!preferred.includes(k) && count > 0) {
      matched.push({ key: k, label: k, count })
    }
  }
  return matched
})

const featureOptions = computed(() => {
  let discountCount = 0
  let refCount = 0
  for (const m of props.models) {
    if (kind.value !== 'all' && !m.kinds.includes(kind.value)) continue
    if (m.name.includes('优惠') || m.name.includes('特惠') || (m.pricing.discount != null && m.pricing.discount < 1)) {
      discountCount++
    }
    if (m.reference_image_urls || (m.pricing.video_reference_prices && Object.keys(m.pricing.video_reference_prices).length > 0)) {
      refCount++
    }
  }
  const list = []
  if (discountCount > 0) list.push({ key: 'discount', label: tr('优惠渠道'), count: discountCount })
  if (refCount > 0) list.push({ key: 'reference', label: tr('支持参考图'), count: refCount })
  return list
})

const hasSidebarFilter = computed(() => (
  selectedSeries.value.length > 0 ||
  selectedResolutions.value.length > 0 ||
  selectedFeatures.value.length > 0
))

function resetSidebarFilters() {
  selectedSeries.value = []
  selectedResolutions.value = []
  selectedFeatures.value = []
}

function resetAllFilters() {
  resetSidebarFilters()
  query.value = ''
  kind.value = 'all'
}

function getModelDiscount(m: CatalogModel): number {
  if (m.pricing?.discount != null && typeof m.pricing.discount === 'number' && m.pricing.discount > 0) {
    return m.pricing.discount
  }
  return 1.0
}

function getDiscountRate(discount: number | undefined | null): string {
  if (discount == null) return ''
  const val = Number((discount * 10).toFixed(1))
  return String(val)
}

const filtered = computed(() => {
  const search = query.value.trim().toLocaleLowerCase()
  return props.models.filter(model => {
    if (kind.value !== 'all' && !model.kinds.includes(kind.value)) return false
    if (search) {
      const matchSearch = [model.name, model.id, model.image_model_type, model.video_model_type]
        .some(value => value?.toLocaleLowerCase().includes(search))
      if (!matchSearch) return false
    }
    if (selectedSeries.value.length > 0) {
      const s = getModelSeries(model)
      if (!selectedSeries.value.includes(s)) return false
    }
    if (selectedResolutions.value.length > 0) {
      const res = getModelResolutions(model)
      if (!selectedResolutions.value.some(r => res.has(r))) return false
    }
    if (selectedFeatures.value.length > 0) {
      for (const feat of selectedFeatures.value) {
        if (feat === 'discount') {
          const isDisc = model.name.includes('优惠') || model.name.includes('特惠') || (model.pricing.discount != null && model.pricing.discount < 1)
          if (!isDisc) return false
        } else if (feat === 'reference') {
          const hasRef = Boolean(model.reference_image_urls || (model.pricing.video_reference_prices && Object.keys(model.pricing.video_reference_prices).length > 0))
          if (!hasRef) return false
        }
      }
    }
    return true
  }).sort((left, right) => {
    if (sort.value === 'newest') return Number(right.id.slice(3)) - Number(left.id.slice(3))
    const byName = collator.compare(left.name, right.name) || collator.compare(left.id, right.id)
    if (sort.value === 'name') return byName
    if (sort.value === 'name-desc') return -byName
    // Default (按模型排序): 倍率越低的越靠前
    const leftDisc = getModelDiscount(left)
    const rightDisc = getModelDiscount(right)
    if (leftDisc !== rightDisc) {
      return leftDisc - rightDisc
    }
    return byName
  })
})

const groups = computed(() => {
  if (sort.value !== 'default' || kind.value !== 'all') return [{ kind: '', models: filtered.value }]
  return categories.value.filter(value => value !== 'all')
    .map(value => ({ kind: value, models: filtered.value.filter(model => model.kinds[0] === value) }))
    .filter(group => group.models.length)
})

function count(value: string) {
  return value === 'all' ? props.models.length : props.models.filter(model => model.kinds.includes(value)).length
}

function icon(value: string) {
  return { image: Image, video: Film }[value] ?? Braces
}

function price(value: number) {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 }).format(value)
}

function isResolution(label: string): boolean {
  return /^\d+p|4k|\d+(\.\d+)?k$/i.test(label)
}

function compareTiers(left: string, right: string) {
  const size = (value: string) => Number.parseFloat(value) * (/k$/i.test(value) ? 1000 : 1)
  return size(left) - size(right) || collator.compare(left, right)
}

function pricingRows(model: CatalogModel) {
  const pricing = model.pricing
  const rows: Array<{ label: string; value: number; unit: string; reference?: boolean }> = []
  const unit = model.kinds.includes('image') ? tr('张') : pricing.billing_unit === 'second' ? tr('秒')
    : pricing.billing_unit === 'minute' ? tr('分钟') : tr('百万 token')
  for (const [field, label] of [
    ['input_price_per_1m', tr('输入单价')], ['output_price_per_1m', tr('输出单价')], ['cache_input_price_per_1m', tr('缓存输入')],
  ] as const) {
    const value = pricing[field]
    if (value != null) rows.push({ label, value, unit: tr('百万 token') })
  }
  for (const [label, value] of Object.entries(pricing.prices ?? {}).sort(([a], [b]) => compareTiers(a, b))) {
    rows.push({ label, value, unit })
  }
  if (pricing.price_per_minute != null) rows.push({ label: tr('标准单价'), value: pricing.price_per_minute, unit: tr('分钟') })
  for (const tier of pricing.tiers ?? []) rows.push({ label: `≤${tier.short_side_max}p · ≤${tier.fps_max}fps`, value: tier.price, unit: tr('分钟') })
  for (const [tier, value] of Object.entries(pricing.video_reference_prices ?? {}).sort(([a], [b]) => compareTiers(a, b))) {
    rows.push({ label: `${tr('参考视频')} · ${tier}`, value, unit, reference: true })
  }
  return rows
}

async function copyId(id: string) {
  try {
    await navigator.clipboard.writeText(id)
    copiedId.value = id
    notice.success(tr('已复制'))
    setTimeout(() => { if (copiedId.value === id) copiedId.value = '' }, 2000)
  } catch {
    notice.error(tr('请选中文字后复制'))
  }
}

function onModelAction(model: CatalogModel) {
  location.hash = `#/platform/docs?model=${encodeURIComponent(model.id)}`
  notice.info(tr('已打开模型 {p0} 接口文档', { p0: model.id }))
}
</script>

<template>
  <div class="model-directory">
    <section v-if="!models.length" class="catalog-initial-empty">
      <Grid3X3 :size="32" aria-hidden="true"/>
      <h2>{{ tr('尚未配置可用模型') }}</h2>
      <p>{{ tr(canManage ? '这是全新平台。添加供应商地址、API Key 和模型配置并启用后，模型会显示在这里。' : loggedIn ? '平台暂未提供可用模型，请联系管理员配置并启用模型。' : '平台尚未配置可用模型。管理员登录后可添加并启用模型。') }}</p>
      <div class="console-inline"><RouterLink v-if="canManage" class="catalog-setup-link" to="/settings">{{ tr('前往模型配置') }}</RouterLink><RouterLink v-else-if="!loggedIn" class="catalog-setup-link" to="/login">{{ tr('登录控制台') }}</RouterLink><RouterLink to="/platform/docs">{{ tr('查看接入文档') }}</RouterLink></div>
    </section>
    <template v-else>
    <!-- SVG Defs for 3D Art -->

    <!-- Top Toolbar -->
    <div class="catalog-toolbar">
      <div class="filters" role="group" :aria-label="tr('模型类型')">
        <button
          v-for="value in categories"
          :key="value"
          class="filter-pill"
          :aria-pressed="kind === value"
          @click="kind = value"
        >
          <component :is="icon(value)" v-if="value !== 'all'" :size="15" aria-hidden="true" />
          {{ labels[value] }}<span class="pill-badge">{{ count(value) }}</span>
        </button>
      </div>

      <div class="catalog-controls">
        <label class="catalog-search">
          <Search :size="15" aria-hidden="true" />
          <input
            v-model="query"
            type="search"
            :aria-label="tr('搜索模型')"
            :placeholder="tr('搜索模型名称或模型 ID')"
          >
          <button v-if="query" type="button" :aria-label="tr('清空搜索')" @click="query = ''">
            <X :size="13" />
          </button>
        </label>

        <div class="catalog-sort-box">
          <AppSelect v-model="sort" :options="sortOptions" :ariaLabel="tr('模型排序')" density="compact" />
        </div>

        <div class="catalog-view-modes" role="group" :aria-label="tr('视图模式')">
          <button
            type="button"
            class="view-mode-btn"
            :class="{ 'is-active': viewMode === 'grid' }"
            :aria-pressed="viewMode === 'grid'"
            :title="tr('大卡片视图')"
            @click="viewMode = 'grid'"
          >
            <LayoutGrid :size="15" />
          </button>
          <button
            type="button"
            class="view-mode-btn"
            :class="{ 'is-active': viewMode === 'compact' }"
            :aria-pressed="viewMode === 'compact'"
            :title="tr('紧凑网格视图')"
            @click="viewMode = 'compact'"
          >
            <Grid3X3 :size="15" />
          </button>
          <button
            type="button"
            class="view-mode-btn"
            :class="{ 'is-active': viewMode === 'list' }"
            :aria-pressed="viewMode === 'list'"
            :title="tr('列表视图')"
            @click="viewMode = 'list'"
          >
            <List :size="15" />
          </button>
        </div>
      </div>
    </div>

    <!-- Main Two-Column Layout -->
    <div class="catalog-layout">
      <!-- Left Sidebar -->
      <aside class="catalog-sidebar">
        <div class="sidebar-header">
          <span class="sidebar-title">{{ tr('筛选') }}</span>
          <button
            v-if="hasSidebarFilter"
            type="button"
            class="sidebar-quick-reset"
            :title="tr('重置筛选')"
            @click="resetSidebarFilters"
          >
            <SlidersHorizontal :size="14" aria-hidden="true" />
          </button>
        </div>

        <div class="sidebar-body">
          <!-- 模型系列 -->
          <div v-if="seriesOptions.length" class="sidebar-group">
            <h4 class="sidebar-group-title">{{ tr('模型系列') }}</h4>
            <label v-for="item in seriesOptions" :key="item.key" class="sidebar-checkbox-label">
              <input type="checkbox" :value="item.key" v-model="selectedSeries">
              <span class="checkbox-indicator" aria-hidden="true"></span>
              <span class="checkbox-text">{{ item.label }}</span>
              <span class="checkbox-count">({{ item.count }})</span>
            </label>
          </div>

          <!-- 分辨率 -->
          <div v-if="resolutionOptions.length" class="sidebar-group">
            <h4 class="sidebar-group-title">{{ tr('分辨率') }}</h4>
            <label v-for="item in resolutionOptions" :key="item.key" class="sidebar-checkbox-label">
              <input type="checkbox" :value="item.key" v-model="selectedResolutions">
              <span class="checkbox-indicator" aria-hidden="true"></span>
              <span class="checkbox-text">{{ item.label }}</span>
              <span class="checkbox-count">({{ item.count }})</span>
            </label>
          </div>

          <!-- 特性 -->
          <div v-if="featureOptions.length" class="sidebar-group">
            <h4 class="sidebar-group-title">{{ tr('特性') }}</h4>
            <label v-for="item in featureOptions" :key="item.key" class="sidebar-checkbox-label">
              <input type="checkbox" :value="item.key" v-model="selectedFeatures">
              <span class="checkbox-indicator" aria-hidden="true"></span>
              <span class="checkbox-text">{{ item.label }}</span>
              <span class="checkbox-count">({{ item.count }})</span>
            </label>
          </div>

          <!-- 重置按钮 -->
          <button
            type="button"
            class="reset-filters-btn"
            @click="resetAllFilters"
          >
            <RotateCcw :size="13" aria-hidden="true" />
            <span>{{ tr('重置筛选') }}</span>
          </button>
        </div>
      </aside>

      <!-- Right Main Content -->
      <div class="catalog-content">
        <div class="catalog-meta-row">
          <p class="catalog-result" role="status">{{ tr('共 {p0} 个模型', { p0: filtered.length }) }}</p>
        </div>

        <template v-if="filtered.length">
          <section v-for="group in groups" :key="group.kind" class="catalog-group">
            <h2 v-if="group.kind" class="catalog-group-title">
              <component :is="icon(group.kind)" :size="18" aria-hidden="true" />{{ labels[group.kind] }}<span>{{ group.models.length }}</span>
            </h2>
            <div class="catalog" :class="`is-${viewMode}`">
              <article
                v-for="model in group.models"
                :key="model.id"
                class="model-card"
                :data-model-id="model.id"
              >

                <!-- Top Row: Kind Badge -->
                <div class="model-card-heading">
                  <span class="model-kind-pill" :class="`is-${model.kinds[0]}`">
                    <component :is="icon(model.kinds[0] ?? '')" :size="13" :stroke-width="2" aria-hidden="true" />
                    <span>{{ model.kinds.map(value => labels[value]).join(' / ') }}</span>
                  </span>
                  <span v-if="model.pricing.discount != null && model.pricing.discount < 1" class="model-discount-pill-top">
                    <Flame :size="12" class="flame-icon-top" aria-hidden="true" />
                    <span>{{ tr('官方价 {p0}折', { p0: getDiscountRate(model.pricing.discount) }) }}</span>
                  </span>
                </div>

                <!-- Model Title -->
                <h3 :title="model.name">{{ model.name }}</h3>

                <!-- Model ID & Capabilities -->
                <div class="model-meta-bar">
                  <button
                    class="model-id"
                    type="button"
                    :aria-label="tr('复制模型 ID {p0}', { p0: model.id })"
                    @click="copyId(model.id)"
                  >
                    <code>{{ model.id }}</code>
                    <Check v-if="copiedId === model.id" :size="12" />
                    <Copy v-else :size="12" />
                  </button>

                  <div class="model-capabilities">
                    <span v-if="model.kinds.includes('image') && model.reference_image_urls" class="tag-ref">{{ tr('支持参考图') }}</span>
                    <span v-if="model.tool_calls" class="tag-tool">{{ tr('工具调用') }}</span>
                    <span v-if="model.json_output" class="tag-json">{{ tr('结构化输出') }}</span>
                  </div>
                </div>

                <!-- Pricing Rows -->
                <dl class="model-prices">
                  <template v-for="row in pricingRows(model).filter(row => !row.reference)" :key="row.label">
                    <div class="price-line">
                      <dt><Monitor v-if="model.kinds.includes('video') && isResolution(row.label)" :size="12" class="price-icon" aria-hidden="true" />{{ row.label }}</dt>
                      <dd><strong>¥{{ price(row.value) }}</strong><span> / {{ row.unit }}</span></dd>
                    </div>
                  </template>
                </dl>

                <!-- Reference Pricing -->
                <details v-if="model.pricing.input_image || model.pricing.video_reference_prices" class="reference-prices">
                  <summary>{{ tr('参考素材价格') }}<ChevronDown :size="13" aria-hidden="true" /></summary>
                  <dl class="model-prices">
                    <template v-for="row in pricingRows(model).filter(row => row.reference)" :key="row.label">
                      <div class="price-line"><dt>{{ row.label }}</dt><dd><strong>¥{{ price(row.value) }}</strong><span> / {{ row.unit }}</span></dd></div>
                    </template>
                  </dl>
                  <p v-if="model.pricing.input_image">{{ tr('输入图前 {p0} 张免费，之后 ¥{p1} / 张', { p0: model.pricing.input_image.first_free, p1: price(model.pricing.input_image.price_per_image) }) }}</p>
                </details>

                <!-- Card Footer -->
                <div class="model-card-footer">
                  <div class="footer-multiplier">
                    <div v-if="model.pricing.discount != null && model.pricing.discount < 1" class="official-discount-badge">
                      <div class="discount-flame-box">
                        <Flame :size="15" class="flame-svg" aria-hidden="true" />
                      </div>
                      <div class="discount-content">
                        <span class="discount-title">{{ tr('官方价') }}</span>
                        <div class="discount-rate-row">
                          <span class="discount-large-num">{{ getDiscountRate(model.pricing.discount) }}</span>
                          <span class="discount-unit-text">{{ tr('折') }}</span>
                          <span class="discount-raw-pill">×{{ model.pricing.discount }}</span>
                        </div>
                      </div>
                    </div>
                    <div v-else class="standard-pricing-badge">
                      <span class="standard-pricing-text">{{ tr('官方标准价') }}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    class="model-action-btn"
                    :title="tr('查看接口调用文档')"
                    :aria-label="tr('查看接口调用文档')"
                    @click="onModelAction(model)"
                  >
                    <ArrowRight :size="14" aria-hidden="true" />
                  </button>
                </div>
              </article>
            </div>
          </section>
        </template>

        <div v-else class="catalog-empty">
          <Search :size="32" aria-hidden="true" />
          <h2>{{ models.length ? tr('没有找到匹配的模型') : tr('暂无可用模型') }}</h2>
          <p v-if="models.length">{{ tr('请尝试调整搜索关键词或重置筛选条件') }}</p>
          <button type="button" @click="resetAllFilters">{{ tr('清除筛选') }}</button>
        </div>
      </div>
    </div>
    </template>
  </div>
</template>

<style scoped>
.model-directory { min-width: 0; width: 100%; }
.catalog-initial-empty { display:flex; flex-direction:column; align-items:flex-start; gap:16px; padding:40px 32px; border:1px solid var(--app-border); border-radius:8px; background:var(--app-surface); color:var(--app-text-secondary); }
.catalog-initial-empty h2 { margin:0; color:var(--app-text); font-size:20px; }
.catalog-initial-empty p { max-width:64ch; margin:0; line-height:1.8; }
.catalog-initial-empty .console-inline { gap:20px; flex-wrap:wrap; }
.catalog-setup-link { display:inline-flex; align-items:center; min-height:40px; padding:8px 16px; border-radius:6px; background:var(--app-primary); color:var(--app-on-primary)!important; }
@media(max-width:640px) { .catalog-initial-empty { padding:28px 20px; } }
.art-svg-defs { position: absolute; width: 0; height: 0; overflow: hidden; }

/* Top Toolbar */
.catalog-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
}

/* Category Filter Pills */
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.filter-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 38px;
  padding: 0 16px;
  border: 1px solid var(--app-border);
  border-radius: 6px;
  background: var(--app-surface);
  color: var(--app-text-secondary);
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all .16s ease;
}
.filter-pill .pill-badge {
  display: inline-block;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  padding: 1px 7px;
  border-radius: 6px;
  background: var(--app-surface-muted);
  color: inherit;
  margin-inline-start: 2px;
}
.filter-pill:hover {
  background: var(--app-surface-hover);
  border-color: var(--app-border-strong);
  color: var(--app-text);
}
.filter-pill[aria-pressed="true"] {
  background: var(--app-primary);
  border-color: var(--app-accent, #6366f1);
  color: var(--app-on-primary);
  font-weight: 600;
  box-shadow:none;
}
.filter-pill[aria-pressed="true"] .pill-badge {
  background: rgba(255, 255, 255, 0.25);
  color: var(--app-on-primary);
}

/* Right Controls */
.catalog-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.catalog-search {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  width: 250px;
  padding: 0 14px;
  border-radius: 6px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  color: var(--app-text-secondary);
  transition: border-color .16s, box-shadow .16s;
}
.catalog-search:focus-within {
  border-color: var(--app-accent);
  box-shadow:none;
}
.model-directory .catalog-search input {
  width: 100%;
  min-width: 0;
  padding: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--app-text);
  font: inherit;
  font-size: 13px;
}
.catalog-search input::-webkit-search-cancel-button { display: none; }
.catalog-search button {
  display: grid;
  place-items: center;
  padding: 3px;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.catalog-sort-box :deep(.app-select__button) {
  border-radius: 6px !important;
  min-height: 38px;
  padding: 0 14px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  font-size: 13px;
  font-weight: 500;
  color: var(--app-text);
}
.catalog-sort-box :deep(.app-select__button:hover) {
  border-color: var(--app-border-strong);
  background: var(--app-surface-hover);
}

.catalog-view-modes {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px;
  border-radius: 10px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
}
.view-mode-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--app-text-secondary);
  cursor: pointer;
  transition: all .16s ease;
}
.view-mode-btn:hover {
  color: var(--app-text);
  background: var(--app-surface-hover);
}
.view-mode-btn.is-active {
  background: var(--app-primary);
  color: var(--app-on-primary);
  box-shadow:none;
}

/* Two-Column Layout */
.catalog-layout {
  display: flex;
  align-items: flex-start;
  gap: 24px;
  margin-top: 10px;
}

/* Sidebar */
.catalog-sidebar {
  width: 200px;
  flex-shrink: 0;
  padding: 18px 16px;
  border-radius: 14px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--app-border);
}
.sidebar-title {
  font-size: 14px;
  font-weight: 650;
  color: var(--app-text);
}
.sidebar-quick-reset {
  display: grid;
  place-items: center;
  padding: 4px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--app-text-secondary);
  cursor: pointer;
}
.sidebar-quick-reset:hover {
  color: var(--app-accent);
  background: var(--app-surface-hover);
}
.sidebar-body {
  padding-top: 14px;
}
.sidebar-group {
  margin-bottom: 20px;
}
.sidebar-group-title {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 650;
  color: var(--app-text);
}
.sidebar-checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 9px;
  font-size: 13px;
  color: var(--app-text);
  cursor: pointer;
  user-select: none;
}
.sidebar-checkbox-label input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}
.checkbox-indicator {
  position: relative;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  border: 1.5px solid var(--app-border-strong);
  background: var(--app-surface);
  display: grid;
  place-items: center;
  flex-shrink: 0;
  transition: all .16s ease;
}
.sidebar-checkbox-label:hover .checkbox-indicator {
  border-color: var(--app-accent);
}
.sidebar-checkbox-label input:checked + .checkbox-indicator {
  background: var(--app-primary);
  border-color: var(--app-accent, #6366f1);
}
.sidebar-checkbox-label input:checked + .checkbox-indicator::after {
  content: '';
  width: 4px;
  height: 8px;
  border: solid #ffffff;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg) translate(-0.5px, -0.5px);
}
.sidebar-checkbox-label input:focus-visible + .checkbox-indicator {
  outline: 2px solid var(--app-accent);
  outline-offset: 2px;
}
.checkbox-text {
  color: var(--app-text);
  font-size: 13px;
}
.checkbox-count {
  color: var(--app-text-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  margin-inline-start: 2px;
  opacity: 0.85;
}

.reset-filters-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  margin-top: 8px;
  padding: 8px 12px;
  border: 1px solid var(--app-border);
  border-radius: 6px;
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all .16s ease;
}
.reset-filters-btn:hover {
  border-color: var(--app-accent);
  color: var(--app-accent);
  background: var(--app-accent-soft);
}

/* Main Content */
.catalog-content {
  flex: 1;
  width: 100%;
  min-width: 0;
  container-type: inline-size;
}
.catalog-meta-row {
  margin-bottom: 12px;
}
.catalog-result {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: 13px;
  font-weight: 500;
}

.catalog-group {
  margin-top: 14px;
}
.catalog-group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 14px;
  color: var(--app-text);
  font-size: 15px;
  font-weight: 650;
}
.catalog-group-title span {
  margin-inline-start: 2px;
  color: var(--app-text-secondary);
  font-size: 12px;
  font-weight: 400;
}

/* Card Grid Modes */
.catalog {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  align-items: stretch;
}
.catalog.is-compact {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.catalog.is-list {
  grid-template-columns: 1fr;
  gap: 10px;
}

/* Model Card */
.model-card {
  position: relative;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: 20px 22px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface);
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
  overflow: hidden;
}
.model-card:hover {
  border-color: color-mix(in srgb, var(--app-accent) 45%, var(--app-border));
  box-shadow:none;
  transform:none;
}

/* 3D Art */
.model-card-art {
  position: absolute;
  top: 10px;
  right: 12px;
  pointer-events: none;
  opacity: 0.9;
}

/* Heading & Badge */
.model-card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.model-discount-pill-top {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 6px;
  background:var(--app-warning-soft);
  color: var(--app-on-primary);
  font-size: 11px;
  font-weight: 700;
  box-shadow:none;
  letter-spacing: 0.3px;

}
.flame-icon-top {
  color: var(--app-on-primary);
  flex-shrink: 0;
}
.model-kind-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  background: color-mix(in srgb, var(--app-accent) 12%, transparent);
  color: var(--app-accent);
}
.model-kind-pill.is-video {
  background: color-mix(in srgb, #8b5cf6 12%, transparent);
  color: var(--app-accent);
}
.model-kind-pill.is-image {
  background: color-mix(in srgb, #6366f1 12%, transparent);
  color: var(--app-accent);
}
.model-kind-pill.is-text {
  background: color-mix(in srgb, #a855f7 12%, transparent);
  color: var(--app-accent);
}

.model-card h3 {
  margin: 0 0 8px;
  min-height: 44px;
  font-size: 15px;
  line-height: 1.4;
  font-weight: 650;
  color: var(--app-text);
  letter-spacing: -0.01em;
  overflow-wrap: anywhere;
}

/* Meta Bar: ID + Tags */
.model-meta-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.model-id {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 7px;
  border: 1px solid var(--app-border);
  border-radius: 5px;
  color: var(--app-text-secondary);
  background: var(--app-surface-muted);
  cursor: pointer;
  transition: all .16s ease;
}
.model-id code {
  font-family: ui-monospace, monospace;
  font-size: 11px;
}
.model-id:hover {
  color: var(--app-accent);
  border-color: var(--app-accent);
}

.model-capabilities {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 5px;
}
.model-capabilities span {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
  font-size: 11px;
}
.tag-ref {
  color: var(--app-accent) !important;
  background: color-mix(in srgb, var(--app-accent) 10%, transparent) !important;
}

/* Pricing Rows */
.model-prices {
  margin: 0;
  flex: 1;
}
.price-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 5px 0;
}
.price-line dt {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--app-text-secondary);
  font-size: 12px;
}
.price-icon {
  color: var(--app-text-secondary);
  opacity: 0.8;
}
.price-line dd {
  margin: 0;
  white-space: nowrap;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: var(--app-text-secondary);
}
.price-line strong {
  color: var(--app-text);
  font-size: 14px;
  font-weight: 600;
}
.price-line dd span {
  color: var(--app-text-secondary);
  font-size: 11px;
}

/* Reference Pricing Accordion */
.reference-prices {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--app-border);
}
.reference-prices summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  list-style: none;
  color: var(--app-text-secondary);
  font-size: 12px;
  cursor: pointer;
}
.reference-prices summary::-webkit-details-marker { display: none; }
.reference-prices summary svg { transition: transform .16s ease; }
.reference-prices[open] summary svg { transform: rotate(180deg); }
.reference-prices[open] summary { margin-bottom: 8px; }
.reference-prices p {
  margin: 8px 0 0;
  color: var(--app-text-secondary);
  font-size: 11px;
  line-height: 1.5;
}

/* Card Footer */
.model-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--app-border);
}
.footer-multiplier {
  min-height: 40px;
  display: flex;
  align-items: center;
}
.official-discount-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border-radius: 10px;
  background:var(--app-warning-soft);
  border: 1px solid rgba(249, 115, 22, 0.35);
  box-shadow:none;
  transition: all 0.2s ease;
}
.official-discount-badge:hover {
  transform:none;
  box-shadow:none;
  border-color: rgba(249, 115, 22, 0.55);
}
.discount-flame-box {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background:var(--app-warning-soft);
  color: var(--app-on-primary);
  display: grid;
  place-items: center;
  flex-shrink: 0;
  box-shadow:none;
}
.flame-svg {
  color: var(--app-on-primary);
}
.discount-content {
  display: flex;
  flex-direction: column;
  gap: 1px;
  line-height: 1.1;
}
.discount-title {
  font-size: 10px;
  font-weight: 600;
  color: var(--app-text-secondary);
  letter-spacing: 0.5px;
}
.discount-rate-row {
  display: flex;
  align-items: baseline;
  gap: 2px;
}
.discount-large-num {
  font-size: 20px;
  font-weight: 900;
  color: var(--creation-warning);
  line-height: 1;
}
.discount-unit-text {
  font-size: 13px;
  font-weight: 800;
  color: var(--creation-warning);
  margin-right: 4px;
}
.discount-raw-pill {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(249, 115, 22, 0.16);
  color: var(--creation-warning);
  line-height: 1.2;
}

:global([data-app-theme="dark"]) .official-discount-badge {
  background:var(--app-warning-soft);
  border-color: rgba(249, 115, 22, 0.45);
  box-shadow:none;
}
:global([data-app-theme="dark"]) .discount-large-num,
:global([data-app-theme="dark"]) .discount-unit-text {
  color: var(--creation-warning);
}
:global([data-app-theme="dark"]) .discount-raw-pill {
  background: rgba(249, 115, 22, 0.25);
  color: var(--creation-warning);
}

.standard-pricing-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
}
.standard-pricing-text {
  font-size: 11px;
  color: var(--app-text-secondary);
  font-weight: 500;
}


.model-action-btn {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 0;
  background: var(--app-primary);
  color: var(--app-on-primary);
  cursor: pointer;
  transition: transform .16s ease, box-shadow .16s ease;
}
.model-action-btn:hover {
  transform:none;
  box-shadow:none;
}

/* Compact / List Modes */
.catalog.is-compact .model-card {
  padding: 16px;
}
.catalog.is-compact .model-card h3 {
  font-size: 14px;
  min-height: 38px;
}
.catalog.is-compact .model-card-art {
  display: none;
}

.catalog.is-list .model-card {
  flex-direction: column;
  align-items: stretch;
  padding: 14px 20px;
  gap: 12px;
}
.catalog.is-list .model-card-heading {
  justify-content: flex-start;
  margin: 0;
}
.catalog.is-list .model-kind-pill {
  white-space: nowrap;
  flex-shrink: 0;
}
.catalog.is-list .model-discount-pill-top {
  display: none;
}
.catalog.is-list .model-card h3 {
  min-height: 0;
  margin: 0;
}
.catalog.is-list .model-card-art {
  display: none;
}
.catalog.is-list .model-card-footer {
  margin-top: 0;
  padding-top: 10px;
  gap: 16px;
}
.catalog.is-list .model-meta-bar,
.catalog.is-list > .model-card > .model-prices {
  margin: 0;
}
.catalog.is-list .discount-flame-box { display: none; }
.catalog.is-list .discount-content { flex-direction: row; align-items: center; gap: 8px; }
.catalog.is-list .discount-large-num { font-size: 14px; }
.catalog.is-list .discount-title { font-size: 12px; }
.catalog.is-list .official-discount-badge { padding: 4px 8px; border-radius: 6px; }
.catalog.is-list .reference-prices { margin: 0; }
@container (min-width: 620px) {
  .catalog.is-list .model-card {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    column-gap: 24px;
    row-gap: 10px;
    align-items: start;
  }
  .catalog.is-list .model-card-heading { grid-column: 1; grid-row: 1; }
  .catalog.is-list .model-card h3 { grid-column: 1; grid-row: 2; }
  .catalog.is-list .model-meta-bar { grid-column: 1; grid-row: 3; }
  .catalog.is-list > .model-card > .model-prices { grid-column: 2; grid-row: 1 / span 3; }
  .catalog.is-list .reference-prices,
  .catalog.is-list .model-card-footer { grid-column: 1 / -1; }
}

/* Empty State */
.catalog-empty {
  padding: 70px 20px;
  text-align: center;
  color: var(--app-text-secondary);
}
.catalog-empty h2 {
  font-size: 16px;
  font-weight: 600;
  color: var(--app-text);
  margin: 12px 0 6px;
}
.catalog-empty p {
  font-size: 13px;
  margin: 0 0 16px;
}
.catalog-empty button {
  border: 1px solid var(--app-border);
  padding: 8px 18px;
  border-radius: 6px;
  background: var(--app-surface);
  color: var(--app-accent);
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all .16s ease;
}
.catalog-empty button:hover {
  border-color: var(--app-accent);
  background: var(--app-accent-soft);
}

button:focus-visible, summary:focus-visible, input:focus-visible {
  outline: 2px solid var(--app-accent);
  outline-offset: 2px;
}

/* Responsive */
@media (max-width: 1180px) {
  .catalog { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .catalog.is-compact { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .catalog-layout { flex-direction: column; }
  .catalog-sidebar { width: 100%; }
  .catalog.is-compact { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .catalog { grid-template-columns: 1fr; }
  .catalog.is-compact { grid-template-columns: 1fr; }
  .catalog-controls { width: 100%; }
  .catalog-search { flex: 1; width: auto; min-width: 140px; }
  .model-card { padding: 18px; }
  .model-card h3 { min-height: 0; }
  .catalog-group { margin-top: 20px; }
}
@media (prefers-reduced-motion: reduce) {
  *, summary svg { transition: none !important; }
}
</style>

.model-discount-pill-top,.discount-flame-box,.flame-icon-top,.flame-svg{color:var(--creation-warning);background:var(--app-warning-soft)}
.model-card-heading{gap:12px}.model-card h3{padding-right:0!important}.model-card-art{display:none}
