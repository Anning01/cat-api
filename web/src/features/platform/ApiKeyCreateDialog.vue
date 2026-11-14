<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import AppDialog from '@/components/AppDialog.vue'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import AppUnitPrice from '@/components/AppUnitPrice.vue'
import { request } from '@/api'
import { tr } from '@/i18n'
import type { SingleResponse } from '@/types'
import type { CatalogModel } from './ModelCatalog.vue'
import type { CreatedApiKey } from './apiKeys'
import { getModelDiscount, getDiscountRate, pricingRows } from './modelPricing'

const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ created: [key: CreatedApiKey] }>()
const dialog = ref<InstanceType<typeof AppDialog>>()
const id = useId()
const name = ref(''), scope = ref('selected'), selected = ref<string[]>([]), query = ref('')
const modelSort = ref('discount')
const duration = ref('never'), customExpiry = ref(''), creating = ref(false), error = ref('')
const models = ref<CatalogModel[]>([]), loading = ref(false), catalogError = ref('')
const errorSummary = ref<HTMLElement>()
let epoch = 0
const options = computed(() => [
  { value:'never', label:tr('永不过期') },
  { value:'7', label:tr('7 天') }, { value:'30', label:tr('30 天') }, { value:'90', label:tr('90 天') },
  { value:'custom', label:tr('自定义时间') },
])
const sortOptions = computed(() => [
  { value:'discount', label:tr('折扣优先') },
  { value:'name', label:tr('名称 A–Z') },
  { value:'newest', label:tr('最近添加') },
])
const collator = new Intl.Collator('zh-CN', { numeric:true, sensitivity:'base' })
const filtered = computed(() => models.value.filter(model =>
  [model.name, model.id, model.alias, model.image_model_type, model.video_model_type].join(' ').toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()))
  .sort((a,b) => {
    if (modelSort.value === 'discount') {
      const difference = getModelDiscount(a)-getModelDiscount(b)
      if (difference) return difference
    }
    if (modelSort.value === 'newest') return collator.compare(b.id,a.id)
    return collator.compare(a.name,b.name)||collator.compare(a.id,b.id)
  }))
const kindNames: Record<string,string> = { image:'图片', video:'视频', text:'文本', media_processing:'画质增强', asr:'语音识别' }

async function loadModels() {
  const current = ++epoch; loading.value = true; catalogError.value = ''
  try {
    const result = await request<SingleResponse<CatalogModel[]>>('/platform/catalog')
    if (current === epoch) models.value = result.data
  } catch (cause) { if (current === epoch) catalogError.value = cause instanceof Error ? cause.message : tr('加载失败') }
  finally { if (current === epoch) loading.value = false }
}
watch(open, value => {
  if (!value) { ++epoch; return }
  name.value = ''; scope.value = 'selected'; selected.value = []; query.value = ''
  duration.value = 'never'; modelSort.value = 'discount'; customExpiry.value = ''; error.value = ''; models.value = []
  void loadModels()
}, { immediate:true })
onBeforeUnmount(() => { ++epoch })

async function create() {
  if (creating.value) return
  error.value = ''
  try {
    if (!name.value.trim()) throw new Error(tr('请输入密钥名称'))
    if (scope.value === 'selected' && !selected.value.length) throw new Error(tr('请至少选择一个模型'))
    let expiresAt: string | null = null
    if (duration.value !== 'never') {
      const date = duration.value === 'custom'
        ? new Date(customExpiry.value+':00+08:00')
        : new Date(Date.now()+Number(duration.value)*86400000)
      if (!Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) throw new Error(tr('到期时间必须晚于当前时间'))
      expiresAt = date.toISOString()
    }
    creating.value = true
    const result = await request<SingleResponse<CreatedApiKey>>('/platform/keys', { method:'POST', body:JSON.stringify({
      name:name.value.trim(), allowed_model_ids:scope.value === 'all' ? null : selected.value, expires_at:expiresAt,
    }) })
    open.value = false
    emit('created', result.data)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : tr('创建失败')
    await nextTick(); errorSummary.value?.focus()
  } finally { creating.value = false }
}
</script>

<template>
  <AppDialog ref="dialog" v-model="open" drawer guard-changes class="console-drawer key-create-dialog" :title="tr('创建 API Key')" size="min(900px,100vw)" :close-on-click-modal="!creating" :close-on-press-escape="!creating" :show-close="!creating">
    <form :id="id+'-form'" class="console-form key-create-form" :aria-label="tr('创建 API Key')" @submit.prevent="create">
      <div class="key-settings">
      <label :for="id+'-name'">{{ tr('密钥名称') }}<input :id="id+'-name'" v-model="name" name="key_name" autofocus required maxlength="80" autocomplete="off" :placeholder="tr('例如：我的应用')"/></label>
      <label :for="id+'-duration'">{{ tr('有效期') }}<AppSelect :id="id+'-duration'" v-model="duration" :options="options" :ariaLabel="tr('有效期')"/></label>
      <label v-if="duration==='custom'" class="key-custom-expiry" :for="id+'-expiry'">{{ tr('到期时间（北京时间）') }}<input :id="id+'-expiry'" v-model="customExpiry" name="expires_at" type="datetime-local" required/></label>
      </div>
      <fieldset class="key-fieldset">
        <legend>{{ tr('可用模型') }}</legend>
        <div class="key-scope-options">
          <label :for="id+'-selected'"><input :id="id+'-selected'" v-model="scope" type="radio" name="model_scope" value="selected"/>{{ tr('指定模型') }}</label>
          <label :for="id+'-all'"><input :id="id+'-all'" v-model="scope" type="radio" name="model_scope" value="all"/>{{ tr('全部可用模型') }}</label>
        </div>
        <p v-if="scope==='all'" class="muted">{{ tr('允许调用当前及之后新增的所有模型。') }}</p>
        <p v-else class="key-model-help muted">{{ tr('同名模型以 ID 区分；以下展示当前价格，实际调用按受理时配置结算。') }}</p>
        <div v-if="scope==='selected'" class="key-model-picker">
          <div class="key-model-toolbar"><input v-model="query" type="search" name="model_search" :aria-label="tr('搜索模型')" :placeholder="tr('搜索模型名称或调用名')"/><AppSelect v-model="modelSort" class="key-model-sort" :options="sortOptions" :ariaLabel="tr('模型排序')" density="compact"/><span role="status">{{ tr('已选 {p0} 个',{p0:selected.length}) }}<span class="visually-hidden">{{ tr('当前排序：{p0}，共 {p1} 个模型',{p0:sortOptions.find(option=>option.value===modelSort)?.label||'',p1:filtered.length}) }}</span></span></div>
          <p v-if="loading" role="status" class="muted">{{ tr('正在加载…') }}</p>
          <p v-else-if="catalogError" role="alert" class="console-error">{{ catalogError }} <AppButton size="sm" @click="loadModels">{{ tr('重试') }}</AppButton></p>
          <div v-else class="key-model-options">
            <label v-for="model in filtered" :key="model.id" :for="id+'-'+model.id" class="key-model-option">
              <input :id="id+'-'+model.id" v-model="selected" type="checkbox" name="allowed_models" :value="model.id" :aria-labelledby="id+'-'+model.id+'-name '+id+'-'+model.id+'-public-id'" :aria-describedby="id+'-'+model.id+'-discount '+id+'-'+model.id+'-meta '+id+'-'+model.id+'-prices'"/>
              <span class="key-model-detail">
                <span class="key-model-heading">
                  <strong :id="id+'-'+model.id+'-name'">{{ model.name }}</strong><code :id="id+'-'+model.id+'-public-id'" class="key-model-id">{{ model.alias||model.id }}</code>
                  <span :id="id+'-'+model.id+'-discount'" class="key-model-discount" :class="{'is-discounted':getModelDiscount(model)<1}">{{ getModelDiscount(model)<1?tr('折扣 {p0}折',{p0:getDiscountRate(model.pricing.discount),p1:getModelDiscount(model)}):getModelDiscount(model)>1?tr('计费倍率 {p0}×',{p0:getModelDiscount(model)}):tr('按标价计费') }}</span>
                  <span :id="id+'-'+model.id+'-meta'" class="key-model-meta"><span>{{ model.kinds.map(kind=>tr(kindNames[kind]||kind)).join(' / ') }}</span><code v-if="model.image_model_type||model.video_model_type">{{ model.image_model_type||model.video_model_type }}</code><span v-if="model.concurrency!=null">{{ tr('并发 {p0}',{p0:model.concurrency}) }}</span><span v-if="model.reference_image_urls">{{ tr('支持参考图') }}</span><span v-if="model.tool_calls">{{ tr('工具调用') }}</span><span v-if="model.json_output">{{ tr('结构化输出') }}</span></span>
                </span>
                <span :id="id+'-'+model.id+'-prices'" class="key-model-prices">
                  <span v-for="row in pricingRows(model)" :key="(row.reference?'reference-':'')+row.label" class="key-price-row" :class="{'is-reference':row.reference}"><span class="key-price-label">{{ row.label }}</span><AppUnitPrice :amount="row.value" :multiplier="getModelDiscount(model)" :unit="row.unit"/></span>
                  <span v-if="model.pricing.input_image" class="key-price-row is-reference"><span class="key-price-label">{{ model.pricing.input_image.first_free === 0 ? tr('输入参考图片') : tr('输入图前 {p0} 张免费，之后',{p0:model.pricing.input_image.first_free}) }}</span><AppUnitPrice :amount="model.pricing.input_image.price_per_image" :multiplier="getModelDiscount(model)" :unit="tr('张')"/></span>
                  <span v-if="!pricingRows(model).length&&!model.pricing.input_image" class="key-price-label">{{ tr('价格未配置') }}</span>
                </span>
              </span>
            </label>
            <p v-if="!filtered.length" class="muted">{{ tr(models.length?'没有找到匹配的模型':'暂无可用模型') }}</p>
          </div>
        </div>
      </fieldset>
      <p class="muted">{{ tr('密钥到期后自动失效，模型调用按账户余额结算。') }}</p>
      <p v-if="error" ref="errorSummary" tabindex="-1" role="alert" class="console-error">{{ error }}</p>
    </form>
    <template #footer><AppButton variant="secondary" :disabled="creating" @click="dialog?.requestClose()">{{ tr('取消') }}</AppButton><AppButton type="submit" :form="id+'-form'" variant="primary" :loading="creating">{{ tr('创建') }}</AppButton></template>
  </AppDialog>
</template>

<style scoped>
.key-settings { display:grid; grid-template-columns:minmax(0,1fr) 200px; gap:16px; }
.key-settings > label { display:grid; gap:7px; min-width:0; font-size:13px; color:var(--app-text-secondary); }
.key-custom-expiry { grid-column:1 / -1; }
.key-fieldset { min-width:0; margin:0; padding:0; border:0; }
.key-fieldset legend { margin-bottom:10px; font-size:13px; color:var(--app-text-secondary); }
.key-scope-options { display:flex; flex-wrap:wrap; gap:8px 20px; margin-bottom:12px; }
.key-scope-options label { display:inline-flex; align-items:center; gap:7px; min-height:32px; font-size:13px; white-space:nowrap; }
.key-scope-options input { width:16px; height:16px; flex:0 0 16px; margin:0; accent-color:var(--app-primary); }
.key-model-picker { border:1px solid var(--app-border); border-radius:8px; overflow:clip; }
.key-model-toolbar { display:flex; align-items:center; gap:8px; padding:8px; border-bottom:1px solid var(--app-border); }
.key-model-toolbar input { flex:1; min-width:0; }
.key-model-sort { flex:0 0 124px; }
.key-model-toolbar span { white-space:nowrap; color:var(--app-text-secondary); font-size:12px; font-variant-numeric:tabular-nums; }
.key-model-help { margin-bottom:12px!important; }
.key-model-options { max-height:clamp(200px,calc(100dvh - 460px),380px); overflow:auto; overscroll-behavior:contain; padding:2px 8px; }
.key-model-option { display:grid; grid-template-columns:16px minmax(0,1fr); align-items:start; gap:8px; min-height:48px; padding:7px 8px; border-bottom:1px solid var(--app-border); border-radius:4px; cursor:pointer; }
.key-model-option:last-of-type { border-bottom:0; }
.key-model-option:hover { background:var(--app-surface-hover); }
.key-model-option:has(input:checked) { background:var(--app-accent-soft); }
.key-model-option input { width:16px; height:16px; margin:3px 0 0; }
.key-model-detail { display:grid; gap:3px; min-width:0; }
.key-model-heading { display:flex; flex-wrap:wrap; align-items:baseline; gap:2px 8px; }
.key-model-heading > strong { font-size:13px; font-weight:600; line-height:1.4; overflow-wrap:anywhere; }
.key-model-id { color:var(--app-text-secondary); font:11px ui-monospace,monospace; }
.key-model-discount { padding:2px 6px; border-radius:5px; color:var(--app-text-secondary); background:var(--app-surface-muted); font-size:11px; }
.key-model-discount.is-discounted { color:var(--creation-warning); background:var(--app-warning-soft); }
.key-model-meta { display:flex; flex:1 1 180px; align-items:baseline; flex-wrap:wrap; gap:2px 8px; color:var(--app-text-secondary); font-size:11px; line-height:1.4; }
.key-model-meta code { font:11px ui-monospace,monospace; overflow-wrap:anywhere; }
.key-model-prices { display:flex; flex-wrap:wrap; align-items:baseline; gap:2px 12px; line-height:1.4; }
.key-price-row { display:inline-flex; align-items:baseline; flex-wrap:wrap; gap:2px 5px; min-width:0; }
.key-model-prices :deep(.unit-price) { gap:2px 4px; }
.key-model-prices :deep(.unit-price strong) { font-size:12px; }
.key-price-label { color:var(--app-text-secondary); font-size:12px; }
.key-model-options p, .key-model-picker > p { padding:12px; }
@media(max-width:640px) { .key-settings { grid-template-columns:minmax(0,1fr); } .key-model-sort { flex-basis:112px; } .key-model-options { max-height:min(320px,40dvh); } }
@media(pointer:coarse) { .key-scope-options label { min-height:48px; } }
</style>
