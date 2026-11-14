<script lang="ts">
import type { ModelPricing } from '@/types'

export interface CatalogModel {
  id: string
  name: string
  alias?: string | null
  kinds: string[]
  image_model_type?: string
  video_model_type?: string
  reference_image_urls?: boolean
  tool_calls?: boolean
  json_output?: boolean
  pricing: ModelPricing
  concurrency?: number
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
  X,
} from 'lucide-vue-next'
import { tr } from '@/i18n'
import { notice } from '@/shared/notice'
import AppUnitPrice from '@/components/AppUnitPrice.vue'
import AppSelect from '@/components/AppSelect.vue'
import { getModelDiscount, getDiscountRate, pricingRows } from './modelPricing'

const props = defineProps<{ models: CatalogModel[]; canManage?: boolean; loggedIn?: boolean }>()
const kind = ref('all')
const query = ref('')
const sort = ref('default')
const viewMode = ref<'grid' | 'compact' | 'list'>('grid')
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
  if (model.pricing.billing_unit === 'pixel_tier') {
    for (const size of ['1K', '1.5K', '2K']) set.add(size)
  } else {
    for (const k of Object.keys(model.pricing.prices ?? {})) set.add(norm(k))
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

const filtered = computed(() => {
  const search = query.value.trim().toLocaleLowerCase()
  return props.models.filter(model => {
    if (kind.value !== 'all' && !model.kinds.includes(kind.value)) return false
    if (search) {
      const matchSearch = [model.name, model.id, model.alias, model.image_model_type, model.video_model_type]
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
  if (viewMode.value !== 'list' || sort.value !== 'default' || kind.value !== 'all') return [{ kind: '', models: filtered.value }]
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

function isResolution(label: string): boolean {
  return /^\d+p|4k|\d+(\.\d+)?k$/i.test(label)
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
  location.hash = `#/platform/docs?model=${encodeURIComponent(model.alias||model.id)}`
  notice.info(tr('已打开模型 {p0} 接口文档', { p0: model.name }))
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
            :placeholder="tr('搜索模型名称或调用名')"
          >
          <button v-if="query" type="button" :aria-label="tr('清空搜索')" @click="query = ''">
            <X :size="13" />
          </button>
        </label>

        <div class="catalog-sort-box">
          <AppSelect v-model="sort" :options="sortOptions" :ariaLabel="tr('模型排序')" density="compact" />
        </div>


      </div>
    </div>

    <!-- Persistent filters and model cards -->
    <div class="catalog-layout">
      <!-- Detailed filters -->
      <aside class="catalog-sidebar" :aria-label="tr('筛选')">
        <div class="sidebar-header">
          <span class="sidebar-title">{{ tr('筛选') }}</span>
          <button
            v-if="hasSidebarFilter"
            type="button"
            class="sidebar-quick-reset"
            :title="tr('重置筛选')"
            :aria-label="tr('重置筛选')"
            @click="resetSidebarFilters"
          >
            <RotateCcw :size="14" aria-hidden="true" />
          </button>
        </div>

        <div class="catalog-view-settings"><span>{{ tr('视图模式') }}</span>
        <div class="catalog-view-modes" role="group" :aria-label="tr('视图模式')">
          <button
            type="button"
            class="view-mode-btn"
            :class="{ 'is-active': viewMode === 'grid' }"
            :aria-pressed="viewMode === 'grid'"
            :aria-label="tr('大卡片视图')"
            @click="viewMode = 'grid'"
          >
            <LayoutGrid :size="15" />
          </button>
          <button
            type="button"
            class="view-mode-btn"
            :class="{ 'is-active': viewMode === 'compact' }"
            :aria-pressed="viewMode === 'compact'"
            :aria-label="tr('紧凑网格视图')"
            @click="viewMode = 'compact'"
          >
            <Grid3X3 :size="15" />
          </button>
          <button
            type="button"
            class="view-mode-btn"
            :class="{ 'is-active': viewMode === 'list' }"
            :aria-pressed="viewMode === 'list'"
            :aria-label="tr('列表视图')"
            @click="viewMode = 'list'"
          >
            <List :size="15" />
          </button>
        </div>
        </div>
        <div class="sidebar-body">
          <!-- 模型系列 -->
          <div v-if="seriesOptions.length" class="sidebar-group">
            <h3 class="sidebar-group-title">{{ tr('模型系列') }}</h3>
            <label v-for="item in seriesOptions" :key="item.key" class="sidebar-checkbox-label">
              <input type="checkbox" :value="item.key" v-model="selectedSeries">
              <span class="checkbox-indicator" aria-hidden="true"></span>
              <span class="checkbox-text">{{ item.label }}</span>
              <span class="checkbox-count">({{ item.count }})</span>
            </label>
          </div>

          <!-- 分辨率 -->
          <div v-if="resolutionOptions.length" class="sidebar-group">
            <h3 class="sidebar-group-title">{{ tr('分辨率') }}</h3>
            <label v-for="item in resolutionOptions" :key="item.key" class="sidebar-checkbox-label">
              <input type="checkbox" :value="item.key" v-model="selectedResolutions">
              <span class="checkbox-indicator" aria-hidden="true"></span>
              <span class="checkbox-text">{{ item.label }}</span>
              <span class="checkbox-count">({{ item.count }})</span>
            </label>
          </div>

          <!-- 特性 -->
          <div v-if="featureOptions.length" class="sidebar-group">
            <h3 class="sidebar-group-title">{{ tr('特性') }}</h3>
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

      <!-- Models -->
      <div class="catalog-content">
        <p class="visually-hidden" role="status">{{ tr('共 {p0} 个模型', { p0: filtered.length }) }}</p>

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
                  <span v-if="getModelDiscount(model) < 1" class="model-discount-pill-top">
                    <Flame :size="12" class="flame-icon-top" aria-hidden="true" />
                    <span>{{ tr('官方价 {p0}折', { p0: getDiscountRate(model.pricing.discount) }) }}</span>
                  </span>
                </div>

                <!-- Model Title -->
                <component :is="group.kind ? 'h3' : 'h2'" class="model-title" :title="model.name">{{ model.name }}</component>

                <!-- Model ID & Capabilities -->
                <div class="model-meta-bar">
                  <button
                    class="model-id"
                    type="button"
                    :aria-label="tr('复制模型调用名 {p0}', { p0: model.alias||model.id })"
                    @click="copyId(model.alias||model.id)"
                  >
                    <code>{{ model.alias||model.id }}</code>
                    <Check v-if="copiedId === (model.alias||model.id)" :size="12" />
                    <Copy v-else :size="12" />
                  </button>

                  <div class="model-capabilities">
                    <span v-if="model.kinds.includes('image') && model.reference_image_urls" class="tag-ref">{{ tr('支持参考图') }}</span>
                    <span v-if="model.tool_calls" class="tag-tool">{{ tr('工具调用') }}</span>
                    <span v-if="model.json_output" class="tag-json">{{ tr('结构化输出') }}</span>
                  </div>
                  <div class="model-card-footer">
                    <button
                      type="button"
                      class="model-action-btn"
                      :title="tr('查看接口调用文档')"
                      :aria-label="tr('接口文档')+' · '+model.name"
                      @click="onModelAction(model)"
                    >
                      {{ tr('接口文档') }}<ArrowRight :size="14" aria-hidden="true" />
                    </button>
                  </div>
                </div>

                <!-- Pricing Rows -->
                <dl class="model-prices">
                  <template v-for="row in pricingRows(model).filter(row => !row.reference)" :key="row.label">
                    <div class="price-line">
                      <dt><Monitor v-if="model.kinds.includes('video') && isResolution(row.label)" :size="12" class="price-icon" aria-hidden="true" />{{ row.label }}</dt>
                      <dd><AppUnitPrice :amount="row.value" :multiplier="getModelDiscount(model)" :unit="row.unit"/></dd>
                    </div>
                  </template>
                </dl>

                <!-- Reference Pricing -->
                <details v-if="model.pricing.input_image || model.pricing.video_reference_prices" class="reference-prices">
                  <summary>{{ tr('参考素材价格') }}<ChevronDown :size="13" aria-hidden="true" /></summary>
                  <dl class="model-prices">
                    <template v-for="row in pricingRows(model).filter(row => row.reference)" :key="row.label">
                      <div class="price-line"><dt>{{ row.label }}</dt><dd><AppUnitPrice :amount="row.value" :multiplier="getModelDiscount(model)" :unit="row.unit"/></dd></div>
                    </template>
                  </dl>
                  <p v-if="model.pricing.input_image">{{ model.pricing.input_image.first_free === 0 ? tr('输入参考图片') : tr('输入图前 {p0} 张免费，之后', { p0: model.pricing.input_image.first_free }) }} <AppUnitPrice :amount="model.pricing.input_image.price_per_image" :multiplier="getModelDiscount(model)" :unit="tr('张')"/></p>
                </details>
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
.model-directory { min-width: 0; width: 100%; container:model-directory / inline-size; }
.catalog-initial-empty { display:flex; flex-direction:column; align-items:flex-start; gap:16px; padding:32px; border:1px solid var(--app-border); border-radius:12px; background:var(--app-surface); color:var(--app-text-secondary); }
.catalog-initial-empty h2 { margin:0; color:var(--app-text); font-size:20px; }
.catalog-initial-empty p { max-width:64ch; margin:0; }
.catalog-initial-empty .console-inline { gap:20px; flex-wrap:wrap; }
.catalog-setup-link { display:inline-flex; align-items:center; min-height:40px; padding:8px 16px; border-radius:6px; background:var(--app-primary); color:var(--app-on-primary)!important; }

.catalog-toolbar { display:flex; align-items:center; flex-wrap:wrap; gap:8px 16px; margin-block-end:12px; }
.filters { display:flex; flex:1 1 400px; align-items:center; gap:4px; min-width:0; overflow-x:auto; }
.filter-pill { display:inline-flex; flex-shrink:0; align-items:center; gap:5px; min-height:34px; padding:0 8px; border:1px solid transparent; border-radius:8px; background:transparent; color:var(--app-text-secondary); font:inherit; font-size:13px; white-space:nowrap; cursor:pointer; }
.pill-badge { font-size:11px; font-variant-numeric:tabular-nums; padding:0 3px; }
.filter-pill:hover { color:var(--app-text); background:var(--app-surface-muted); }
.filter-pill[aria-pressed=true] { background:var(--app-accent-soft); color:var(--app-accent); border-color:var(--app-accent); }
.catalog-controls { display:flex; flex:1 1 380px; justify-content:flex-end; align-items:center; gap:8px; min-width:0; }
.catalog-search { display:flex; flex:1; align-items:center; gap:8px; min-width:120px; max-width:260px; min-height:36px; padding-inline:10px; border:1px solid var(--app-border); border-radius:8px; background:var(--app-surface); color:var(--app-text-secondary); }
.catalog-search:focus-within { outline:2px solid var(--app-accent); outline-offset:2px; }
.model-directory .catalog-search input { flex:1; width:100%; min-width:0; min-height:32px; padding:0; border:0; outline:0; background:transparent; color:var(--app-text); font:inherit; font-size:13px; }
.catalog-search input::-webkit-search-cancel-button { display:none; }
.catalog-search button { display:grid; place-items:center; min-width:24px; min-height:24px; padding:0; border:0; background:transparent; color:inherit; cursor:pointer; }
.catalog-sort-box { flex:0 0 auto; }
.catalog-sort-box :deep(.app-select__trigger) { min-height:36px; border-color:var(--app-border); }

.catalog-layout { min-width:0; display:grid; grid-template-columns:220px minmax(0,1fr); align-items:start; gap:16px; }
.catalog-sidebar { position:sticky; inset-block-start:12px; min-width:0; max-block-size:calc(100dvh - 200px); overflow-y:auto; overscroll-behavior:contain; padding:16px; border:1px solid var(--app-border); border-radius:12px; background:var(--app-surface); }
.sidebar-header, .catalog-view-settings { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.sidebar-header { margin-block-end:12px; }
.sidebar-title { font-size:14px; font-weight:600; }
.sidebar-quick-reset { display:grid; place-items:center; min-width:32px; min-height:32px; background:transparent; color:var(--app-accent); border-radius:6px; cursor:pointer; }
.sidebar-quick-reset:hover { background:var(--app-accent-soft); }
.catalog-view-settings { justify-content:flex-start; flex-wrap:wrap; gap:8px; margin-block-end:16px; font-size:13px; color:var(--app-text-secondary); }
.catalog-view-settings > span { white-space:nowrap; }
.catalog-view-modes { display:inline-flex; gap:4px; padding:3px; border-radius:8px; background:var(--app-surface-muted); }
.view-mode-btn { display:grid; place-items:center; width:32px; height:32px; border:0; border-radius:6px; background:transparent; color:var(--app-text-secondary); cursor:pointer; }
.view-mode-btn:hover { color:var(--app-accent); }
.view-mode-btn.is-active { background:var(--app-surface); color:var(--app-accent); }
.sidebar-body { display:grid; grid-template-columns:minmax(0,1fr); gap:16px; }
.sidebar-group-title { margin:0 0 8px; font-size:13px; font-weight:600; }
.sidebar-checkbox-label { display:flex; align-items:center; gap:8px; min-height:30px; font-size:13px; cursor:pointer; }
.sidebar-checkbox-label input { position:absolute; opacity:0; width:0; height:0; }
.checkbox-indicator { position:relative; display:grid; place-items:center; width:16px; height:16px; flex-shrink:0; border:1px solid var(--app-border-strong); border-radius:4px; background:var(--app-surface); }
.sidebar-checkbox-label input:checked + .checkbox-indicator { background:var(--app-primary); border-color:var(--app-primary); }
.sidebar-checkbox-label input:checked + .checkbox-indicator::after { content:''; width:4px; height:8px; border:solid var(--app-on-primary); border-width:0 2px 2px 0; transform:rotate(45deg) translate(-.5px,-.5px); }
.sidebar-checkbox-label input:focus-visible + .checkbox-indicator { outline:2px solid var(--app-accent); outline-offset:2px; }
.checkbox-text { flex:1; min-width:0; overflow-wrap:anywhere; }
.checkbox-count { flex-shrink:0; color:var(--app-text-secondary); font-size:12px; font-variant-numeric:tabular-nums; }
.reset-filters-btn { display:inline-flex; align-items:center; gap:6px; grid-column:1 / -1; justify-self:start; min-height:32px; padding:0 10px; border:1px solid var(--app-border); border-radius:6px; background:var(--app-surface-muted); color:var(--app-text-secondary); font:inherit; font-size:12px; cursor:pointer; }

.catalog-content { min-width:0; container:catalog-content / inline-size; }
.catalog-group + .catalog-group { margin-block-start:20px; }
.catalog-group-title { display:flex; align-items:center; gap:8px; margin-block-end:12px; }
.catalog-group-title span { color:var(--app-text-secondary); font-size:12px; }
.catalog { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr)); gap:12px; align-items:stretch; }
.catalog.is-compact { grid-template-columns:repeat(auto-fill,minmax(min(100%,240px),1fr)); }
.catalog.is-list { grid-template-columns:1fr; }
.model-card { display:flex; flex-direction:column; gap:6px; min-width:0; padding:16px; border:1px solid var(--app-border); border-radius:12px; background:var(--app-surface); }
.model-card:hover { border-color:var(--app-accent); }
.model-card-heading { display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.model-kind-pill, .model-discount-pill-top { display:inline-flex; align-items:center; gap:4px; min-height:22px; padding:2px 6px; border-radius:5px; font-size:11px; font-weight:500; }
.model-kind-pill { background:var(--app-accent-soft); color:var(--app-accent); }
.model-discount-pill-top { background:var(--app-warning-soft); color:var(--creation-warning); }
.model-title { margin:0; color:var(--app-text); font-size:15px; font-weight:650; line-height:1.5; overflow-wrap:anywhere; }
.model-meta-bar { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.model-id { max-width:100%; min-width:0; display:inline-flex; align-items:center; gap:6px; min-height:24px; padding:2px 6px; border:1px solid transparent; border-radius:5px; background:var(--app-surface-muted); color:var(--app-text-secondary); cursor:pointer; }
.model-id code { font:11px ui-monospace,monospace; white-space:normal; overflow-wrap:anywhere; text-align:start; }
.model-id:hover { color:var(--app-accent); border-color:var(--app-accent); }
.model-capabilities { display:flex; flex-wrap:wrap; gap:4px; }
.model-capabilities span { font-size:11px; color:var(--app-text-secondary); }
.model-capabilities span + span::before { content:'·'; margin-inline-end:4px; }
.model-prices { margin:0; }
.model-card > .model-prices { margin-block-start:4px; padding-block-start:8px; border-block-start:1px solid var(--app-border); }
.price-line { display:flex; align-items:baseline; justify-content:space-between; flex-wrap:wrap; gap:2px 8px; padding-block:2px; }
.price-line dt { display:inline-flex; align-items:center; gap:4px; color:var(--app-text-secondary); font-size:12px; }
.price-line dd { min-width:0; margin:0; margin-inline-start:auto; font-size:12px; font-variant-numeric:tabular-nums; }
.reference-prices { margin-block-start:0; }
.reference-prices summary { display:flex; align-items:center; gap:6px; min-height:24px; width:fit-content; list-style:none; color:var(--app-text-secondary); font-size:12px; cursor:pointer; }
.reference-prices summary::-webkit-details-marker { display:none; }
.reference-prices[open] summary svg { transform:rotate(180deg); }
.reference-prices p { margin:4px 0 0; color:var(--app-text-secondary); font-size:12px; }
.model-card-footer { display:flex; justify-content:flex-end; margin-inline-start:auto; }
.model-action-btn { display:inline-flex; align-items:center; gap:6px; min-height:28px; padding:0 6px; border:0; border-radius:6px; background:transparent; color:var(--app-accent); font:inherit; font-size:12px; cursor:pointer; }
.model-action-btn:hover { background:var(--app-accent-soft); }
.catalog.is-compact .model-card { padding:12px; gap:6px; }
.catalog.is-compact .model-title { font-size:15px; }
@container catalog-content (min-width:640px) {
  .catalog.is-list .model-card { display:grid; grid-template-columns:minmax(0,1fr) minmax(240px,.8fr); gap:6px 24px; align-items:center; }
  .catalog.is-list .model-card-heading { grid-column:1; grid-row:1; }
  .catalog.is-list .model-title { grid-column:1; grid-row:2; }
  .catalog.is-list .model-meta-bar { grid-column:1; grid-row:3; }
  .catalog.is-list .model-card > .model-prices { grid-column:2; grid-row:1 / span 3; border:0; margin:0; padding:0; }
  .catalog.is-list .reference-prices { grid-column:2; }
}
@container model-directory (max-width:640px) {
  .catalog-layout { grid-template-columns:minmax(0,1fr); gap:12px; }
  .catalog-sidebar { position:static; max-block-size:240px; }
}
.catalog-empty { padding:40px 16px; text-align:center; color:var(--app-text-secondary); }
.catalog-empty h2 { margin:12px 0 6px; }
.catalog-empty button { padding:8px 16px; border:1px solid var(--app-border); border-radius:6px; background:var(--app-surface-muted); color:var(--app-accent); cursor:pointer; }
button:focus-visible, summary:focus-visible { outline:2px solid var(--app-accent); outline-offset:2px; }
@media (max-width:640px) {
  .catalog-toolbar { gap:8px; }
  .filters, .catalog-controls { flex-basis:100%; }
  .catalog-search { min-width:100px; max-width:none; }
  .catalog-search svg { display:none; }
  .model-directory .catalog-search input { font-size:16px; }
  .catalog-sort-box :deep(.app-select__trigger) { font-size:12px!important; padding-inline:6px; }
  .model-card { padding:16px; }
}
@media (pointer:coarse) {
  .filter-pill, .model-action-btn, .model-id, .view-mode-btn, .reference-prices summary, .sidebar-checkbox-label { min-height:44px; }
  .view-mode-btn { min-width:44px; }
  .sidebar-quick-reset { min-width:44px; min-height:44px; }
}
@media (prefers-reduced-motion:no-preference) {
  .model-card { transition:border-color 160ms ease-out; }
  .model-action-btn svg { transition:transform 160ms ease-out; }
  .model-action-btn:hover svg { transform:translateX(2px); }
}
</style>
