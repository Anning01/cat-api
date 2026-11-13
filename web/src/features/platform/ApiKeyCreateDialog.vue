<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import AppDialog from '@/components/AppDialog.vue'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import { request } from '@/api'
import { tr } from '@/i18n'
import type { SingleResponse } from '@/types'
import type { CatalogModel } from './ModelCatalog.vue'
import type { CreatedApiKey } from './apiKeys'

const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ created: [key: CreatedApiKey] }>()
const dialog = ref<InstanceType<typeof AppDialog>>()
const id = useId()
const name = ref(''), scope = ref('selected'), selected = ref<string[]>([]), query = ref('')
const duration = ref('30'), customExpiry = ref(''), creating = ref(false), error = ref('')
const models = ref<CatalogModel[]>([]), loading = ref(false), catalogError = ref('')
const errorSummary = ref<HTMLElement>()
let epoch = 0
const options = computed(() => [
  { value:'7', label:tr('7 天') }, { value:'30', label:tr('30 天') }, { value:'90', label:tr('90 天') },
  { value:'never', label:tr('永不过期') }, { value:'custom', label:tr('自定义时间') },
])
const filtered = computed(() => models.value.filter(model =>
  (model.name+' '+model.id).toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))

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
  duration.value = '30'; customExpiry.value = ''; error.value = ''; models.value = []
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
  <AppDialog ref="dialog" v-model="open" drawer guard-changes class="console-drawer key-create-dialog" :title="tr('创建 API Key')" size="min(560px,100vw)" :close-on-click-modal="!creating" :close-on-press-escape="!creating" :show-close="!creating">
    <form :id="id+'-form'" class="console-form key-create-form" :aria-label="tr('创建 API Key')" @submit.prevent="create">
      <label :for="id+'-name'">{{ tr('密钥名称') }}<input :id="id+'-name'" v-model="name" name="key_name" autofocus required maxlength="80" autocomplete="off" :placeholder="tr('例如：我的应用')"/></label>
      <fieldset class="key-fieldset">
        <legend>{{ tr('可用模型') }}</legend>
        <div class="key-scope-options">
          <label :for="id+'-selected'"><input :id="id+'-selected'" v-model="scope" type="radio" name="model_scope" value="selected"/>{{ tr('指定模型') }}</label>
          <label :for="id+'-all'"><input :id="id+'-all'" v-model="scope" type="radio" name="model_scope" value="all"/>{{ tr('全部可用模型') }}</label>
        </div>
        <p v-if="scope==='all'" class="muted">{{ tr('允许调用当前及之后新增的所有模型。') }}</p>
        <div v-else class="key-model-picker">
          <div class="key-model-toolbar"><input v-model="query" type="search" name="model_search" :aria-label="tr('搜索模型')" :placeholder="tr('搜索模型名称或模型 ID')"/><span>{{ tr('已选 {p0} 个',{p0:selected.length}) }}</span></div>
          <p v-if="loading" role="status" class="muted">{{ tr('正在加载…') }}</p>
          <p v-else-if="catalogError" role="alert" class="console-error">{{ catalogError }} <AppButton size="sm" @click="loadModels">{{ tr('重试') }}</AppButton></p>
          <div v-else class="key-model-options">
            <label v-for="model in filtered" :key="model.id" :for="id+'-'+model.id" class="key-model-option"><input :id="id+'-'+model.id" v-model="selected" type="checkbox" name="allowed_models" :value="model.id"/><span>{{ model.name }}<code>{{ model.id }}</code></span></label>
            <p v-if="!filtered.length" class="muted">{{ tr(models.length?'没有找到匹配的模型':'暂无可用模型') }}</p>
          </div>
        </div>
      </fieldset>
      <label :for="id+'-duration'">{{ tr('有效期') }}<AppSelect :id="id+'-duration'" v-model="duration" :options="options" :ariaLabel="tr('有效期')"/></label>
      <label v-if="duration==='custom'" :for="id+'-expiry'">{{ tr('到期时间（北京时间）') }}<input :id="id+'-expiry'" v-model="customExpiry" name="expires_at" type="datetime-local" required/></label>
      <p class="muted">{{ tr('密钥到期后自动失效，模型调用按账户余额结算。') }}</p>
      <p v-if="error" ref="errorSummary" tabindex="-1" role="alert" class="console-error">{{ error }}</p>
    </form>
    <template #footer><AppButton variant="secondary" :disabled="creating" @click="dialog?.requestClose()">{{ tr('取消') }}</AppButton><AppButton type="submit" :form="id+'-form'" variant="primary" :loading="creating">{{ tr('创建') }}</AppButton></template>
  </AppDialog>
</template>

<style scoped>
.key-fieldset { min-width:0; margin:0; padding:0; border:0; }
.key-fieldset legend { margin-bottom:10px; font-size:13px; color:var(--app-text-secondary); }
.key-scope-options { display:flex; flex-wrap:wrap; gap:8px 20px; margin-bottom:12px; }
.key-scope-options label { display:inline-flex; align-items:center; gap:7px; min-height:32px; font-size:13px; white-space:nowrap; }
.key-scope-options input { width:16px; height:16px; flex:0 0 16px; margin:0; accent-color:var(--app-primary); }
.key-model-picker { border:1px solid var(--app-border); border-radius:8px; overflow:clip; }
.key-model-toolbar { display:flex; align-items:center; gap:8px; padding:8px; border-bottom:1px solid var(--app-border); }
.key-model-toolbar input { flex:1; min-width:0; }
.key-model-toolbar span { white-space:nowrap; color:var(--app-text-secondary); font-size:12px; font-variant-numeric:tabular-nums; }
.key-model-options { max-height:220px; overflow:auto; overscroll-behavior:contain; padding:4px 8px; }
.key-model-option { display:flex; align-items:center; gap:10px; min-height:48px; padding:8px; border-radius:6px; cursor:pointer; }
.key-model-option:hover { background:var(--app-surface-hover); }
.key-model-option input { flex-shrink:0; }
.key-model-option span { min-width:0; font-size:13px; overflow-wrap:anywhere; }
.key-model-option code { display:block; color:var(--app-text-secondary); font:11px ui-monospace,monospace; margin-top:3px; }
.key-model-options p, .key-model-picker > p { padding:12px; }
@media(pointer:coarse) { .key-scope-options label { min-height:48px; } }
</style>
