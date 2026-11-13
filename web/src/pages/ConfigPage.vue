<script setup lang="ts">
import { tr } from '@/i18n'
import ConsolePage from '@/components/ConsolePage.vue'
import AppButton from '@/components/AppButton.vue'
import AppDialog from '@/components/AppDialog.vue'
import ConsoleTable from '@/components/ConsoleTable.vue'
import AppStatusBadge from '@/components/AppStatusBadge.vue'
import AppUnitPrice from '@/components/AppUnitPrice.vue'
import { pricingRows, getDiscountRate, pixelTierLabel } from '@/features/platform/modelPricing'

import { computed, onMounted, ref } from 'vue'
import {
  Bot,
  Eye,
  EyeOff,
  Image,
  KeyRound,
  Pencil,
  Plus,
  Power,
  Server,
  Trash2,
  Video,
  Zap,
  Mic,
} from 'lucide-vue-next'
import AppMultiSelect from '@/components/AppMultiSelect.vue'
import AppIconTile from '@/components/AppIconTile.vue'
import AppSelect from '@/components/AppSelect.vue'
import { api } from '@/api'
import { defaultPricing } from '@/shared/modelPricing'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import type { AiModelConfig, ConfigEnumItem, EnumItem, GenerationCapabilities, ImageApiProtocol, ImageModelType, ModelPricing, VideoGenerationModelType } from '@/types'

type ModelCategoryId = 'llm' | 'image' | 'video' | 'enhancement' | 'asr'

interface ModelCategory {
  id: ModelCategoryId
  label: string
  eyebrow: string
  description: string
  taskTypes: number[]
  icon: typeof Bot
}

const categories: ModelCategory[] = [
  {
    id: 'llm',
    get label() { return tr('LLM 大模型') },
    eyebrow: 'LANGUAGE',
    get description() { return tr('负责剧本理解、人物提取、分镜文本生成与来源视频拆解。') },
    taskTypes: [1, 3, 5, 6, 7],
    icon: Bot,
  },
  {
    id: 'image',
    get label() { return tr('生图模型') },
    eyebrow: 'IMAGE',
    get description() { return tr('负责角色定妆、场景概念图和一致性参考图生成。') },
    taskTypes: [2],
    icon: Image,
  },
  {
    id: 'video',
    get label() { return tr('视频模型') },
    eyebrow: 'VIDEO',
    get description() { return tr('负责分镜片段生成、动态镜头和最终视频合成。') },
    taskTypes: [4],
    icon: Video,
  },
]
categories.push({
  id: 'enhancement', get label() { return tr('视频画质增强') }, eyebrow: 'ENHANCEMENT',
  get description() { return tr('单条视频或成片提升清晰度，按后台配置选择输出档位。') },
  taskTypes: [8], icon: Zap,
})
categories.push({
  id: 'asr', get label() { return tr('语音识别') }, eyebrow: 'SPEECH',
  get description() { return tr('负责视频原声转写、智能字幕与时间轴对齐（火山引擎 SeedASR 2.0 等）。') },
  taskTypes: [9], icon: Mic,
})
const VIDEO_MODEL_PRESETS: Record<VideoGenerationModelType, { baseUrl: string; model: string; protocol: ImageApiProtocol }> = {
  seedance_2: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seedance-2-0-260128', protocol: 'volcengine_ark' },
  seedance_2_fast: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seedance-2-0-fast-260128', protocol: 'volcengine_ark' },
  seedance_2_mini: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seedance-2-0-mini-260615', protocol: 'volcengine_ark' },
  seedance_2_5: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seedance-2-5-260817', protocol: 'volcengine_ark' },
  minimax_h3_autodl: { baseUrl: 'https://autodl.art/api/v1/comfyui', model: 'minimax_h3_zm_u24', protocol: 'autodl' },
  minimax_h3: { baseUrl: 'https://api.minimaxi.com', model: 'MiniMax-H3', protocol: 'minimax' },
  wan_3: { baseUrl: 'https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com', model: 'wan3.0-video', protocol: 'dashscope' },
}

const configs = ref<AiModelConfig[]>([])
const taskTypes = ref<EnumItem[]>([])
const imageModelTypes = ref<ConfigEnumItem[]>([])
const videoModelTypes = ref<ConfigEnumItem[]>([])
const loading = ref(true)
function canManage(item: AiModelConfig) { return item.scope !== 'studio_platform' }
const showCreate = ref(false)
const creating = ref(false)
const editingConfigId = ref<number | null>(null)
const editingSyncedPricing = ref(false)
const syncedVideoBillingUnit = ref<ModelPricing['billing_unit']>()
const showApiKey = ref(false)
const selectedCategoryId = ref<ModelCategoryId>('llm')
const form = ref({ task_types: ['1'], name: '', base_url: '', api_key: '', model: '', api_protocol: 'openai_compatible' as ImageApiProtocol, image_model_type: '' as ImageModelType | '', video_model_type: '' as VideoGenerationModelType | '', concurrency: 1, supports_json_output: false, supports_tool_calls: false, max_context_characters: '' as number | '', thinking: '' as 'enabled' | 'disabled' | '', max_tokens: '' as number | '' })

function configTaskTypes(item: AiModelConfig) {
  return item.task_types?.length ? item.task_types : [item.task_type]
}

const selectedCategory = computed(() => categories.find(item => item.id === selectedCategoryId.value) ?? categories[0])
const isEditing = computed(() => editingConfigId.value !== null)
const selectedConfigs = computed(() => configs.value.filter(item => configTaskTypes(item).some(value => selectedCategory.value.taskTypes.includes(value))))
const taskOptions = computed(() => selectedCategory.value.taskTypes.map(value => ({
  value: String(value),
  label: tr(taskTypes.value.find(item => item.value === value)?.label || '') || ({ get 1() { return tr('内容理解与人物提取') }, get 2() { return tr('角色与场景参考图') }, get 3() { return tr('分镜规划与提示词') }, get 4() { return tr('视频片段生成') }, get 5() { return tr('项目分析') }, get 6() { return tr('重制') }, get 7() { return tr('创作助手') }, get 8() { return tr('视频画质增强') }, get 9() { return tr('语音识别') } }[value] ?? tr('任务 {p0}', { p0: value })),
})))
const imageModelTypeOptions = computed(() => [
  { value: '', label: tr('请选择受支持的模型') },
  ...imageModelTypes.value.map(item => ({ value: String(item.value), label: tr(item.label) })),
])
const videoModelTypeOptions = computed(() => [
  { value: '', label: tr('请选择受支持的视频模型') },
  ...videoModelTypes.value.map(item => ({ value: String(item.value), label: tr(item.label) })),
])
const imageProtocolOptions = computed(() => {
  const allowed = form.value.image_model_type ? generationCapabilities.value.image_protocols?.[form.value.image_model_type] : undefined
  const options = [
    { value: 'openai_compatible', label: tr('OpenAI 兼容（GPT Image / 中转服务）') },
    { value: 'openrouter_compatible', label: tr('OpenRouter 兼容（/images）') },
    { value: 'volcengine_ark', label: tr('火山方舟 Seedream') },
    { value: 'novelvids', label: tr('猫影开放平台') },
  ]
  return allowed ? allowed.flatMap(value => options.filter(option => option.value === value)) : options
})
const thinkingOptions = computed(() => [
  { value: '', label: tr('按模型默认') },
  { value: 'enabled', label: tr('开启思考（enabled）') },
  { value: 'disabled', label: tr('关闭思考（disabled）') },
])

const generationCapabilities = ref<GenerationCapabilities>({ image: {}, video: {} })
const enhancementPricing = ref<NonNullable<ModelPricing['tiers']>>([])
const processingOptions = ref<Record<string, unknown>>({})
const enhancementResolutions = computed(() => generationCapabilities.value.media_processing?.resolutions || [])
function toggleEnhancementResolution(value: string, shortSide: number, enabled: boolean) {
  const current = Array.isArray(processingOptions.value.output_resolutions) ? processingOptions.value.output_resolutions as string[] : ['1080p']
  processingOptions.value.output_resolutions = enabled ? [...new Set([...current, value])] : current.filter(item => item !== value)
  if (enabled && !enhancementPricing.value.some(tier => tier.short_side_max === shortSide)) {
    const preset = generationCapabilities.value.media_processing?.pricing.tiers || []
    enhancementPricing.value.push(...preset.filter(tier => tier.short_side_max === shortSide).map(tier => ({ ...tier })))
  }
}
const asrPrice = ref(0)
const textPricing = ref({ input_price_per_1m: 0, cache_input_price_per_1m: '' as number | '', output_price_per_1m: 0 })
const selectedTextPricingPreset = computed(() => generationCapabilities.value.text_pricing?.[form.value.model.trim().toLowerCase()])
function applyTextPricingPreset() {
  const preset = selectedTextPricingPreset.value
  if (!preset) return
  textPricing.value = {
    input_price_per_1m: preset.input_price_per_1m ?? 0,
    cache_input_price_per_1m: preset.cache_input_price_per_1m ?? '',
    output_price_per_1m: preset.output_price_per_1m ?? 0,
  }
}
const tierPrices = ref<Record<string, number>>({})
const inputImagePricing = ref({ first_free: 1, price_per_image: 0 })
const videoRefPrices = ref<Record<string, number>>({})
const discountPricing = ref({ discount: 1, description: '' })
const imagePreset = computed(() => generationCapabilities.value.image_pricing?.[form.value.image_model_type])
const pixelBilling = ref(false)
function applyImagePreset() {
  const preset = imagePreset.value
  if (!preset?.prices || !preset.input_image) return
  pixelBilling.value = true
  tierPrices.value = { ...preset.prices }
  inputImagePricing.value = { ...preset.input_image }
}
const pricingTierOptions = computed<string[]>(() => {
  if (selectedCategoryId.value === 'image' && pixelBilling.value) return Object.keys(imagePreset.value?.prices ?? {})
  if (selectedCategoryId.value === 'image') return generationCapabilities.value.image[form.value.image_model_type] || []
  if (selectedCategoryId.value === 'video') return selectedVideoProtocol.value?.resolutions
    || generationCapabilities.value.video[form.value.video_model_type] || []
  return []
})
const selectedVideoPricingPreset = computed(() => (
  form.value.video_model_type
    ? generationCapabilities.value.video_pricing?.[form.value.video_model_type]
    : undefined
))
const isSecondBillingVideo = computed(() => (
  selectedCategoryId.value === 'video'
  && (editingSyncedPricing.value ? syncedVideoBillingUnit.value : selectedVideoPricingPreset.value?.billing_unit) === 'second'
))

function applyVideoPricingPreset() {
  const pricing = selectedVideoPricingPreset.value
  tierPrices.value = pricing?.prices ? { ...pricing.prices } : {}
  videoRefPrices.value = pricing?.video_reference_prices
    ? { ...pricing.video_reference_prices }
    : { ...tierPrices.value }
  inputImagePricing.value = pricing?.input_image
    ? { ...pricing.input_image }
    : { first_free: 0, price_per_image: 0 }
}

function iconTone(categoryId: ModelCategoryId) {
  if (categoryId === 'image') return 'image' as const
  if (categoryId === 'video') return 'video' as const
  return 'accent' as const
}

function configsFor(category: ModelCategory) {
  return configs.value.filter(item => configTaskTypes(item).some(value => category.taskTypes.includes(value)))
}

const enabledCount = computed(() => selectedConfigs.value.filter(item => item.is_active).length)
function configPrices(item: AiModelConfig) {
  return item.pricing ? pricingRows({ kinds: [selectedCategoryId.value], pricing: item.pricing }) : []
}

function taskLabel(value: number) {
  return tr(taskTypes.value.find(item => item.value === value)?.label || '') || ({ get 1() { return tr('内容理解') }, get 2() { return tr('参考图生成') }, get 3() { return tr('分镜规划') }, get 4() { return tr('视频生成') }, get 5() { return tr('项目分析') }, get 6() { return tr('重制') }, get 7() { return tr('创作助手') } }[value] ?? tr('任务 {p0}', { p0: value }))
}

function protocolLabel(value: ImageApiProtocol) {
  if (value === 'novelvids') return tr('猫影开放平台')
  if (value === 'volcengine_mediakit') return 'AI MediaKit'
  if (value === 'autodl') return 'AutoDL ComfyUI'
  if (value === 'minimax') return tr('MiniMax 官方')
  if (value === 'dashscope') return tr('阿里云百炼 DashScope')
  if (value === 'volcengine_ark') return tr('火山方舟 Seedream')
  if (value === 'openrouter_compatible') return tr('OpenRouter 兼容')
  return tr('OpenAI 兼容')
}

function videoProtocolFor(modelType: VideoGenerationModelType | ''): ImageApiProtocol {
  return modelType ? VIDEO_MODEL_PRESETS[modelType].protocol : 'volcengine_ark'
}

const videoProtocolOptions = computed(() => {
  const modelType = form.value.video_model_type
  const options = modelType ? generationCapabilities.value.video_protocols?.[modelType] : undefined
  return options?.map(option => ({ ...option, label: tr(option.label) }))
    || [{ value: videoProtocolFor(modelType), label: protocolLabel(videoProtocolFor(modelType)),
      resolutions: generationCapabilities.value.video[modelType] || [] }]
})
const selectedVideoProtocol = computed(() => videoProtocolOptions.value.find(option => option.value === form.value.api_protocol))
const selectedVideoProtocolHint = computed(() => {
  if (form.value.api_protocol === 'novelvids') return tr('使用平台的 /v1 地址、视频模型 ID 和 API Key。')
  if (form.value.video_model_type === 'minimax_h3_autodl') {
    return tr('填写 ComfyUI 分组 Token；模型名称填写工作流 ID。支持参考图和音频，不支持参考视频或首尾帧。')
  }
  if (form.value.video_model_type === 'minimax_h3') {
    return tr('提交到 /v2/video_generation，并从 /v2/query/video_generation/{task_id} 查询结果。')
  }
  if (form.value.video_model_type === 'wan_3') {
    return tr('请将 YOUR_WORKSPACE_ID 替换为百炼业务空间 ID；提交到 video-synthesis，并从 /api/v1/tasks/{task_id} 查询。')
  }
  return tr('提交到 /contents/generations/tasks，并通过任务 ID 异步查询结果。')
})

async function load() {
  loading.value = true
  try {
    const [configResponse, enumResponse, capabilitiesResponse] = await Promise.all([
      api.configs(),
      api.enums(),
      api.generationCapabilities(),
    ])
    configs.value = configResponse.data.items
    taskTypes.value = enumResponse.data.ai_task_type || []
    imageModelTypes.value = enumResponse.data.image_model_type || []
    videoModelTypes.value = enumResponse.data.video_model_type || []
    generationCapabilities.value = capabilitiesResponse.data
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

function openCreate(categoryId: ModelCategoryId = selectedCategoryId.value) {
  editingSyncedPricing.value = false
  pixelBilling.value = false
  selectedCategoryId.value = categoryId
  const category = categories.find(item => item.id === categoryId) ?? categories[0]
  form.value = { task_types: [String(category.taskTypes[0])], name: '', base_url: category.id === 'video' ? 'https://ark.cn-beijing.volces.com/api/v3' : '', api_key: '', model: '', api_protocol: category.id === 'image' || category.id === 'video' ? 'volcengine_ark' : 'openai_compatible', image_model_type: category.id === 'image' ? 'seedream_5_lite' : '', video_model_type: category.id === 'video' ? 'seedance_2' : '', concurrency: 1, supports_json_output: false, supports_tool_calls: false, max_context_characters: '' as number | '', thinking: '' as 'enabled' | 'disabled' | '', max_tokens: '' as number | '' }
  const asrPreset = generationCapabilities.value.audio_recognition
  asrPrice.value = asrPreset?.pricing?.price_per_minute ?? 0
  if (category.id === 'asr' && asrPreset) Object.assign(form.value, { base_url: asrPreset.base_url, model: asrPreset.model, api_protocol: asrPreset.api_protocol })
  textPricing.value = { input_price_per_1m: 0, cache_input_price_per_1m: '', output_price_per_1m: 0 }
  tierPrices.value = category.id === 'llm' || category.id === 'enhancement'
    ? {}
    : defaultPricing(category.id, pricingTierOptions.value).prices ?? {}
  inputImagePricing.value = { first_free: 1, price_per_image: 0 }
  videoRefPrices.value = {}
  if (category.id === 'video') applyVideoPricingPreset()
  if (category.id === 'enhancement') {
    const preset = generationCapabilities.value.media_processing
    if (!preset) { notice.error(tr('画质增强能力尚未加载')); return }
    form.value.base_url = preset.base_url
    form.value.model = preset.model
    form.value.api_protocol = preset.api_protocol
    enhancementPricing.value = (preset.pricing.tiers || []).map(tier => ({ ...tier }))
    processingOptions.value = { ...preset.processing_options }
  }
  discountPricing.value = { discount: 1, description: '' }
  editingConfigId.value = null
  showApiKey.value = false
  showCreate.value = true
}

function openEdit(item: AiModelConfig) {
  editingSyncedPricing.value = item.scope === 'studio_platform'
  pixelBilling.value = item.pricing?.billing_unit === 'pixel_tier'
  syncedVideoBillingUnit.value = item.pricing?.billing_unit
  const category = categories.find(value => value.taskTypes.includes(item.task_type)) ?? categories[0]
  selectedCategoryId.value = category.id
  editingConfigId.value = item.id
  showApiKey.value = false
  form.value = {
    task_types: configTaskTypes(item)
      .filter(taskType => category.taskTypes.includes(taskType))
      .map(String),
    name: item.name,
    base_url: item.base_url || '',
    api_key: item.api_key || '',
    model: item.model || '',
    api_protocol: item.api_protocol || (category.id === 'video' ? videoProtocolFor(item.video_model_type || '') : 'openai_compatible'),
    image_model_type: item.image_model_type || '',
    video_model_type: item.video_model_type || '',
    concurrency: item.concurrency,
    supports_json_output: item.supports_json_output ?? false,
    supports_tool_calls: item.supports_tool_calls ?? false,
    max_context_characters: item.max_context_characters ?? '',
    thinking: item.thinking ?? '',
    max_tokens: item.max_tokens ?? '',
  }
  textPricing.value = item.pricing?.type === 'text'
    ? { input_price_per_1m: item.pricing.input_price_per_1m ?? 0, cache_input_price_per_1m: item.pricing.cache_input_price_per_1m ?? '', output_price_per_1m: item.pricing.output_price_per_1m ?? 0 }
    : { input_price_per_1m: 0, cache_input_price_per_1m: '', output_price_per_1m: 0 }
  asrPrice.value = item.pricing?.price_per_minute ?? 0
  tierPrices.value = item.pricing?.prices ? { ...item.pricing.prices } : {}
  inputImagePricing.value = item.pricing?.input_image
    ? { first_free: item.pricing.input_image.first_free, price_per_image: item.pricing.input_image.price_per_image }
    : { first_free: 1, price_per_image: 0 }
  videoRefPrices.value = item.pricing?.video_reference_prices ? { ...item.pricing.video_reference_prices } : {}
  enhancementPricing.value = (item.pricing?.tiers || []).map(tier => ({ ...tier }))
  processingOptions.value = { ...(item.processing_options || {}) }
  discountPricing.value = {
    discount: item.pricing?.discount ?? 1,
    description: item.pricing?.discount_description ?? '',
  }
  showCreate.value = true
}

function changeImageModelType() {
  if (!imageProtocolOptions.value.some(option => option.value === form.value.api_protocol)) {
    const first = imageProtocolOptions.value[0]
    if (first) form.value.api_protocol = first.value as ImageApiProtocol
  }
}

function changeVideoModelType() {
  if (!form.value.video_model_type) return
  const preset = VIDEO_MODEL_PRESETS[form.value.video_model_type]
  if (form.value.api_protocol === 'novelvids' && videoProtocolOptions.value.some(option => option.value === form.value.api_protocol)) {
    applyVideoPricingPreset()
    return
  }
  form.value.base_url = preset.baseUrl
  form.value.model = preset.model
  form.value.api_protocol = preset.protocol
  applyVideoPricingPreset()
}

function selectVideoProtocol(value: string) {
  if (value === form.value.api_protocol) return
  form.value.api_protocol = value as ImageApiProtocol
  const preset = form.value.video_model_type ? VIDEO_MODEL_PRESETS[form.value.video_model_type] : undefined
  form.value.base_url = preset?.protocol === value ? preset.baseUrl : ''
  form.value.model = preset?.protocol === value ? preset.model : ''
}

function selectImageModelType(value: string) {
  if (form.value.image_model_type === value) return
  form.value.image_model_type = value as ImageModelType | ''
  changeImageModelType()
  pixelBilling.value = false
  tierPrices.value = defaultPricing('image', pricingTierOptions.value).prices ?? {}
  inputImagePricing.value = { first_free: 1, price_per_image: 0 }
  if (imagePreset.value) applyImagePreset()
}

function selectVideoModelType(value: string) {
  form.value.video_model_type = value as VideoGenerationModelType | ''
  changeVideoModelType()
}

function selectImageProtocol(value: string) {
  form.value.api_protocol = value as ImageApiProtocol
}

function selectThinking(value: string) {
  form.value.thinking = value as 'enabled' | 'disabled' | ''
}

async function saveConfig() {
  if (!form.value.task_types.length) {
    notice.error(tr('请至少选择一个能力用途'))
    return
  }
  // 原生 select 的 required 校验由共享选择器接管，避免空模型类型被提交。
  if (selectedCategoryId.value === 'image' && !form.value.image_model_type) {
    notice.error(tr('请选择受支持的模型'))
    return
  }
  if (selectedCategoryId.value === 'image' && pricingTierOptions.value.some(tier =>
    typeof tierPrices.value[tier] !== 'number' || !Number.isFinite(tierPrices.value[tier]) || tierPrices.value[tier]! < 0)) {
    notice.error(tr('请配置全部清晰度档位的输出图单价'))
    return
  }
  if (selectedCategoryId.value === 'video' && !form.value.video_model_type) {
    notice.error(tr('请选择受支持的视频模型'))
    return
  }
  creating.value = true
  try {
    const taskTypes = form.value.task_types.map(Number)
    const tierPriceEntries = (source: Record<string, number>) => Object.fromEntries(
      pricingTierOptions.value.map(tier => {
        const value = source[tier]
        return [tier, typeof value === 'number' && !Number.isNaN(value) ? value : 0]
      })
    )
    let pricing: ModelPricing
    if (selectedCategoryId.value === 'enhancement') {
      pricing = { type: 'media_processing', currency: 'CNY', billing_unit: 'minute', tiers: enhancementPricing.value }
    } else if (selectedCategoryId.value === 'asr') {
      pricing = { type: 'asr', currency: 'CNY', billing_unit: 'minute', price_per_minute: asrPrice.value }
    } else if (selectedCategoryId.value === 'llm') {
      pricing = {
        type: 'text',
        currency: 'CNY',
        input_price_per_1m: Number(textPricing.value.input_price_per_1m) || 0,
        output_price_per_1m: Number(textPricing.value.output_price_per_1m) || 0,
        ...(textPricing.value.cache_input_price_per_1m !== ''
          ? { cache_input_price_per_1m: Number(textPricing.value.cache_input_price_per_1m) }
          : {}),
      }
    } else if (selectedCategoryId.value === 'image') {
      pricing = {
        type: 'image',
        ...(pixelBilling.value ? { billing_unit: 'pixel_tier' as const } : {}),
        currency: 'CNY',
        prices: tierPriceEntries(tierPrices.value),
        input_image: {
          first_free: Number(inputImagePricing.value.first_free) || 0,
          price_per_image: Number(inputImagePricing.value.price_per_image) || 0,
        },
      }
    } else {
      pricing = {
        type: 'video',
        currency: 'CNY',
        billing_unit: isSecondBillingVideo.value ? 'second' : 'token',
        prices: tierPriceEntries(tierPrices.value),
        video_reference_prices: tierPriceEntries(videoRefPrices.value),
      }
      if (isSecondBillingVideo.value) {
        pricing.input_image = {
          first_free: Number(inputImagePricing.value.first_free) || 0,
          price_per_image: Number(inputImagePricing.value.price_per_image) || 0,
        }
      }
    }
    pricing.discount = Number(discountPricing.value.discount) || 1
    const discountDescription = discountPricing.value.description.trim()
    if (discountDescription) pricing.discount_description = discountDescription
    const payload = {
      ...form.value,
      api_protocol: form.value.api_protocol,
      processing_options: selectedCategoryId.value === 'enhancement' ? processingOptions.value : null,
      task_type: taskTypes[0],
      task_types: taskTypes,
      max_context_characters: form.value.max_context_characters || null,
      thinking: form.value.thinking || null,
      max_tokens: form.value.max_tokens || null,
      image_model_type: selectedCategoryId.value === 'image' ? form.value.image_model_type || null : null,
      video_model_type: selectedCategoryId.value === 'video' ? form.value.video_model_type || null : null,
      pricing,
    }
    if (editingConfigId.value !== null) {
      await api.updateConfig(editingConfigId.value, editingSyncedPricing.value ? { pricing } : payload)
    } else {
      await api.createConfig(payload)
    }
    showCreate.value = false
    await load()
    notice.success(isEditing.value ? tr('模型配置已更新') : tr('模型配置已创建'))
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    creating.value = false
  }
}

async function activate(item: AiModelConfig) {
  try {
    await api.activateConfig(item.id)
    await load()
    notice.success(tr('已启用 {p0}', { p0: item.name }))
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function deactivate(item: AiModelConfig) {
  try {
    await api.deactivateConfig(item.id)
    await load()
    notice.success(tr('已停用 {p0}', { p0: item.name }))
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function remove(item: AiModelConfig) {
  if (!await appConfirm({
    title: tr('删除模型配置「{p0}」？', { p0: item.name }),
    get message() { return tr('删除后该模型将无法继续用于新的生成任务。') },
    get confirmLabel() { return tr('删除配置') },
    tone: 'danger',
  })) return
  try {
    await api.deleteConfig(item.id)
    await load()
    notice.success(tr('模型配置已删除'))
  } catch (error) {
    notice.error((error as Error).message)
  }
}

const configDialog=ref<InstanceType<typeof AppDialog>>()
onMounted(()=>{void load()})
</script>

<template>
  <ConsolePage class="model-settings-page" :title="tr('模型配置')" :description="tr('统一管理文本、图片、视频与画质增强模型。')">
    <template #actions><AppButton variant="primary" type="button" @click="openCreate()"><Plus :size="16" />{{ tr('添加模型') }}</AppButton></template>

    <div class="model-category-grid" role="group" :aria-label="tr('模型能力分类')">
      <AppButton v-for="category in categories" :key="category.id" variant="ghost" class="model-category-card" :active="selectedCategoryId===category.id" :aria-pressed="selectedCategoryId===category.id" @click="selectedCategoryId=category.id">
        <component :is="category.icon" :size="16" aria-hidden="true"/><span>{{ category.label }}</span><span class="category-count">{{ configsFor(category).length }}</span>
      </AppButton>
    </div>

    <section class="model-config-section console-table-panel">
      <header class="console-table-toolbar">
        <div class="model-list-heading"><h2>{{ selectedCategory.label }}</h2><span class="model-list-count">{{ tr('共 {p0} 条',{p0:selectedConfigs.length}) }}<span aria-hidden="true"> · </span>{{ tr('已启用') }} {{ enabledCount }}</span></div>
      </header>
      <div v-if="loading" class="model-state" role="status">{{ tr('正在读取模型配置…') }}</div>
      <ConsoleTable v-else-if="selectedConfigs.length" class="model-config-list" :caption="tr('模型配置列表')">
        <thead><tr><th scope="col">{{ tr('模型名称') }}</th><th scope="col">{{ tr('能力与协议') }}</th><th scope="col">{{ tr('计费价格') }}</th><th scope="col" class="numeric">{{ tr('并发') }}</th><th scope="col">{{ tr('状态') }}</th><th scope="col" class="row-actions">{{ tr('操作') }}</th></tr></thead>
        <tbody><tr v-for="item in selectedConfigs" :key="item.id" class="model-config-row">
          <th scope="row"><div class="config-identity"><AppIconTile :tone="iconTone(selectedCategory.id)" size="sm"><component :is="selectedCategory.icon" :size="18"/></AppIconTile><div><div class="config-name"><strong>{{ item.name }}</strong><span v-if="item.pricing?.discount&&item.pricing.discount<1" class="config-discount">{{ tr('{p0} 折',{p0:getDiscountRate(item.pricing.discount)}) }}</span></div><code>{{ item.model||tr('未设置模型名称') }}</code><small>#{{ item.id }}</small></div></div></th>
          <td><div class="config-capabilities"><span>{{ configTaskTypes(item).filter(taskType=>selectedCategory.taskTypes.includes(taskType)).map(taskLabel).join(' · ') }}</span><small>{{ protocolLabel(item.api_protocol) }}<template v-if="selectedCategory.id==='llm'"> · {{ item.supports_json_output?tr('JSON 格式化'):tr('提示词 JSON') }}</template><template v-if="selectedCategory.id==='image'"> · {{ imageModelTypes.find(type=>type.value===item.image_model_type)?.label||tr('未选择受支持类型') }}</template><template v-if="selectedCategory.id==='video'"> · {{ videoModelTypes.find(type=>type.value===item.video_model_type)?.label||tr('未选择受支持类型') }}</template></small></div></td>
          <td><dl v-if="configPrices(item).length" class="config-prices"><div v-for="(price,index) in configPrices(item)" :key="index"><dt>{{ price.label }}</dt><dd><AppUnitPrice :amount="price.value" :multiplier="item.pricing?.discount??1" :unit="price.unit"/></dd></div></dl><span v-else class="muted">{{ tr('未配置价格') }}</span></td>
          <td class="numeric">{{ item.concurrency }}</td>
          <td><AppStatusBadge :tone="item.is_active?'success':'neutral'">{{ tr(item.is_active?'已启用':'已停用') }}</AppStatusBadge></td>
          <td class="row-actions"><div class="config-actions"><template v-if="canManage(item)"><AppButton variant="ghost" size="sm" :title="tr(item.is_active?'停用配置':'启用配置')" @click="item.is_active?deactivate(item):activate(item)"><Power :size="14"/>{{ tr(item.is_active?'停用':'启用') }}</AppButton><AppButton variant="ghost" size="sm" :aria-label="tr('编辑配置')" @click="openEdit(item)"><Pencil :size="14"/>{{ tr('编辑') }}</AppButton><AppButton variant="ghost" size="sm" icon-only class="config-delete" :aria-label="tr('删除配置')" :title="tr('删除配置')" @click="remove(item)"><Trash2 :size="15"/></AppButton></template><span v-else class="official-badge" :title="tr('此配置仅可读取')">{{ tr('只读') }}</span></div></td>
        </tr></tbody>
      </ConsoleTable>
      <div v-else class="model-empty-state"><component :is="selectedCategory.icon" :size="28" aria-hidden="true"/><h3>{{ tr('还没有') }}{{ selectedCategory.label }}</h3><p>{{ selectedCategory.description }}</p><AppButton variant="primary" size="sm" @click="openCreate(selectedCategory.id)"><Plus :size="15"/>{{ tr('添加第一个配置') }}</AppButton></div>
    </section>
    <AppDialog ref="configDialog" v-model="showCreate" class="model-editor-dialog" :title="editingSyncedPricing ? tr('编辑本地价格') : (isEditing ? tr('编辑') : tr('添加')) + selectedCategory.label" width="900px" guard-changes :show-close="!creating" :close-on-click-modal="!creating" :close-on-press-escape="!creating">
      <form class="model-modal" autocomplete="off" @submit.prevent="saveConfig">
        <div v-if="!editingSyncedPricing" class="model-form-grid">
          <label v-if="selectedCategory.taskTypes.length > 1" class="is-full">
            <span>{{ tr('能力用途') }}</span>
            <AppMultiSelect v-model="form.task_types" :ariaLabel="tr('能力用途')" :options="taskOptions" />
            <small>{{ tr('可同时选择多个用途；勾选“重制”表示该模型支持视频输入并可用于来源视频拆解。') }}</small>
          </label>
          <label class="is-full"><span>{{ tr('配置名称') }}</span><input v-model="form.name" name="model-config-name" autofocus required autocomplete="off" :placeholder="tr('例如：豆包 Seed 1.6')" /></label>
          <label class="is-full"><span>Base URL</span><span class="input-with-icon"><Server :size="15" /><input v-model="form.base_url" name="model-service-base-url" required autocomplete="off" inputmode="url" spellcheck="false" placeholder="https://api.example.com/v1" /></span></label>
          <label class="is-full">
            <span>API Key</span>
            <span class="input-with-icon secret-input">
              <KeyRound :size="15" />
              <input v-model="form.api_key" name="model-service-api-key" :type="showApiKey ? 'text' : 'password'" required autocomplete="new-password" autocapitalize="none" spellcheck="false" :placeholder="tr('输入模型服务密钥')" />
              <AppButton variant="ghost" size="sm" icon-only type="button" :aria-label="showApiKey ? tr('隐藏 API Key') : tr('显示 API Key')" :title="showApiKey ? tr('隐藏 API Key') : tr('显示 API Key')" @click="showApiKey = !showApiKey">
                <EyeOff v-if="showApiKey" :size="16" />
                <Eye v-else :size="16" />
              </AppButton>
            </span>
          </label>
          <label><span>{{ tr('模型名称') }}</span><input v-model="form.model" name="model-id" required autocomplete="off" spellcheck="false" :placeholder="tr('模型 ID')" /></label>
          <label><span>{{ tr('并发数') }}</span><input v-model.number="form.concurrency" name="model-concurrency" type="number" min="1" required /></label>
          <label v-if="selectedCategory.id === 'image'" class="is-full">
            <span>{{ tr('生图模型类型') }}</span>
            <AppSelect
              :model-value="form.image_model_type"
              :options="imageModelTypeOptions"
              :ariaLabel="tr('生图模型类型')"
              :menu-z-index="2000"
              @update:model-value="selectImageModelType"
            />
            <small>{{ tr('支持 Seedream 与 GPT Image 系列；清晰度、比例与格式由所选类型的后台能力定义。') }}</small>
          </label>
          <label v-if="selectedCategory.id === 'video'" class="is-full">
            <span>{{ tr('视频模型类型') }}</span>
            <AppSelect
              :model-value="form.video_model_type"
              :options="videoModelTypeOptions"
              :ariaLabel="tr('视频模型类型')"
              :menu-z-index="2000"
              @update:model-value="selectVideoModelType"
            />
            <small>{{ tr('支持 Seedance 系列与 MiniMax H3；分辨率、比例、时长和请求格式由后台能力与适配器定义。') }}</small>
          </label>
          <label v-if="selectedCategory.id === 'video'" class="is-full">
            <span>{{ tr('接口协议') }}</span>
            <AppSelect
              :model-value="form.api_protocol"
              :options="videoProtocolOptions"
              :ariaLabel="tr('视频接口协议')"
              :menu-z-index="2000"
              @update:model-value="selectVideoProtocol"
            />
            <small>{{ selectedVideoProtocolHint }}</small>
          </label>
          <label v-if="selectedCategory.id === 'image'" class="is-full">
            <span>{{ tr('接口协议') }}</span>
            <AppSelect
              :model-value="form.api_protocol"
              :options="imageProtocolOptions"
              :ariaLabel="tr('接口协议')"
              :menu-z-index="2000"
              @update:model-value="selectImageProtocol"
            />
            <small>{{ tr('协议决定请求字段与尺寸适配，不依赖模型名称猜测供应商。') }}</small>
          </label>
          <label v-if="selectedCategory.id === 'llm'">
            <span>{{ tr('上下文字符上限') }}</span>
            <input
              v-model.number="form.max_context_characters"
              name="model-max-context-characters"
              type="number"
              min="1"
              :placeholder="tr('留空表示不预检')"
            />
          </label>
          <label v-if="selectedCategory.id === 'llm'">
            <span>{{ tr('思考模式') }}</span>
            <AppSelect
              :model-value="form.thinking"
              :options="thinkingOptions"
              :ariaLabel="tr('思考模式')"
              :menu-z-index="2000"
              @update:model-value="selectThinking"
            />
            <small>{{ tr('深度思考/推理模型可关闭思考以提速并避免正文被 reasoning 挤占。') }}</small>
          </label>
          <label v-if="selectedCategory.id === 'llm'">
            <span>{{ tr('最大输出 token') }}</span>
            <input
              v-model.number="form.max_tokens"
              name="model-max-tokens"
              type="number"
              min="1"
              :placeholder="tr('留空按模型默认')"
            />
            <small>{{ tr('限制单次请求输出，避免 JSON 因达到 token 上限被截断。') }}</small>
          </label>
          <label v-if="selectedCategory.id === 'llm'" class="is-full json-capability-field">
            <span class="json-capability-copy">
              <strong>{{ tr('结构化 JSON 输出') }}</strong>
              <small>{{ tr('开启后发送 response_format=json_object；关闭后仅使用提示词约束 JSON。') }}</small>
            </span>
            <input v-model="form.supports_json_output" type="checkbox" role="switch" :aria-label="tr('结构化 JSON 输出')" />
          </label>
        </div>

        <label v-if="selectedCategoryId === 'llm' && !editingSyncedPricing" class="model-toggle">
          <input v-model="form.supports_tool_calls" type="checkbox" role="switch" :aria-label="tr('多轮工具调用')" />
          <span>{{ tr('支持多轮工具调用（创作助手必需）') }}</span>
        </label>
        <section v-if="selectedCategoryId === 'enhancement'" class="pricing-editor">
          <span class="pricing-title">{{ tr('增强费用（元 / 输出分钟）') }}</span>
          <div class="enhancement-resolution-options">
            <label v-for="item in enhancementResolutions" :key="item.value"><input type="checkbox" :checked="(Array.isArray(processingOptions.output_resolutions) ? processingOptions.output_resolutions : ['1080p']).includes(item.value)" @change="toggleEnhancementResolution(item.value, item.short_side, ($event.target as HTMLInputElement).checked)" />{{ item.value.toUpperCase() }}</label>
          </div>
          <div class="pricing-grid">
            <label v-for="tier in enhancementPricing" :key="`${tier.short_side_max}:${tier.fps_max}`">
              <span>{{ tier.short_side_max }}p · {{ tr('最高帧率') }} {{ tier.fps_max }} fps</span>
              <input v-model.number="tier.price" type="number" min="0" step="0.01" />
            </label>
          </div>
        </section>
        <section v-if="selectedCategoryId === 'asr'" class="pricing-editor"><span class="pricing-title">{{ tr('语音识别费用（元 / 分钟）') }}</span><div class="pricing-grid"><label><span>{{ tr('每分钟单价') }}</span><input v-model.number="asrPrice" aria-label="ASR price per minute" type="number" min="0" step="0.001" /></label></div></section>
        <section v-else-if="selectedCategoryId === 'llm'" class="pricing-editor">
          <span class="pricing-title">{{ tr('费用设置（元 / 百万 token）') }}</span>
          <AppButton v-if="selectedTextPricingPreset" variant="secondary" size="sm" type="button" @click="applyTextPricingPreset">{{ tr('填入官方基准价') }}</AppButton>
          <div class="pricing-grid">
            <label><span>{{ tr('输入单价') }}</span><input v-model.number="textPricing.input_price_per_1m" type="number" min="0" step="any" required /></label>
            <label><span>{{ tr('缓存命中输入单价（可选）') }}</span><input v-model.number="textPricing.cache_input_price_per_1m" type="number" min="0" step="any" aria-describedby="cache-price-hint" /></label>
            <label><span>{{ tr('输出单价') }}</span><input v-model.number="textPricing.output_price_per_1m" type="number" min="0" step="any" required /></label>
          </div>
          <small id="cache-price-hint">{{ tr('留空按普通输入价计费，填 0 表示缓存命中免费；按接口实际返回的命中 token 计算。') }}</small>
          <small v-if="selectedTextPricingPreset">{{ tr('基准价由后台提供，DeepSeek 固定使用高峰价；填入基准价不改变收费倍率。') }}</small>
        </section>
        <section v-else-if="selectedCategoryId === 'image' && pricingTierOptions.length" class="pricing-editor">
          <span class="pricing-title">{{ tr('输出图费用（元 / 张）') }}</span>
          <AppButton v-if="imagePreset" variant="secondary" size="sm" type="button" @click="applyImagePreset">{{ tr('填入官方像素分档价') }}</AppButton>
          <div class="pricing-grid">
            <label v-for="tier in pricingTierOptions" :key="tier">
              <span>{{ pixelBilling ? pixelTierLabel(tier) : tr('清晰度') + ' ' + tier }}</span>
              <input v-model.number="tierPrices[tier]" type="number" min="0" step="0.01" required />
            </label>
          </div>
          <div class="pricing-sub">
            <span class="pricing-title">{{ tr('输入图费用（图生图）') }}</span>
            <div class="pricing-grid">
              <label><span>{{ tr('免费张数') }}</span><input v-model.number="inputImagePricing.first_free" type="number" min="0" step="1" /></label>
              <label><span>{{ tr('超出单价（元 / 张）') }}</span><input v-model.number="inputImagePricing.price_per_image" type="number" min="0" step="0.01" /></label>
            </div>
          </div>
        </section>
        <section v-else-if="selectedCategoryId === 'video' && pricingTierOptions.length" class="pricing-editor">
          <span class="pricing-title">{{ isSecondBillingVideo ? tr('生成视频（元 / 秒）') : tr('无视频参考（元 / 百万 token）') }}</span>
          <div class="pricing-grid">
            <label v-for="tier in pricingTierOptions" :key="tier">
              <span>{{ tr('分辨率') }} {{ tier }}</span>
              <input v-model.number="tierPrices[tier]" type="number" min="0" step="0.01" />
            </label>
          </div>
          <div class="pricing-sub">
            <span class="pricing-title">{{ isSecondBillingVideo ? tr('输入参考视频（元 / 秒，按输入时长）') : tr('有视频参考（元 / 百万 token）') }}</span>
            <div class="pricing-grid">
              <label v-for="tier in pricingTierOptions" :key="tier">
                <span>{{ tr('分辨率') }} {{ tier }}</span>
                <input v-model.number="videoRefPrices[tier]" type="number" min="0" step="0.01" />
              </label>
            </div>
          </div>
          <div v-if="isSecondBillingVideo" class="pricing-sub">
            <span class="pricing-title">{{ tr('输入参考图片') }}</span>
            <div class="pricing-grid">
              <label><span>{{ tr('免费张数') }}</span><input v-model.number="inputImagePricing.first_free" type="number" min="0" step="1" /></label>
              <label><span>{{ tr('超出单价（元 / 张）') }}</span><input v-model.number="inputImagePricing.price_per_image" type="number" min="0" step="0.01" /></label>
            </div>
            <small>{{ tr('输入音频免费，不计入费用。') }}</small>
          </div>
        </section>

        <section class="pricing-editor">
          <span class="pricing-title">{{ tr('收费倍率（1=原价，0.9=9折，大于 1=加价倍数）') }}</span>
          <div class="pricing-grid">
            <label><span>{{ tr('收费倍率') }}</span><input v-model.number="discountPricing.discount" type="number" min="0.01" step="0.01" required /></label>
            <label><span>{{ tr('折扣描述（可选）') }}</span><input v-model="discountPricing.description" type="text" :placeholder="tr('例如：限时9折')" /></label>
          </div>
        </section>

        <footer><span class="model-modal-hint">{{ tr('关闭（Esc）') }}</span><AppButton variant="secondary" size="sm" type="button" @click="configDialog?.requestClose()">{{ tr('取消') }}</AppButton><AppButton variant="primary" size="sm" type="submit" :loading="creating">{{ creating ? tr('保存中…') : (isEditing ? tr('保存修改') : tr('创建配置')) }}</AppButton></footer>
      </form>
    </AppDialog>
  </ConsolePage>
</template>

<style scoped>
.model-settings-page { display:flex; flex-direction:column; height:100%; min-height:100%; color:var(--app-text); }
.model-settings-page :deep(.console-page-header) { flex-shrink:0; }
.official-badge { color:var(--app-text-secondary); font-size:12px; }
.model-category-grid { display:flex; flex-shrink:0; align-items:center; gap:4px; padding-block:0 12px; margin-bottom:12px; border-bottom:1px solid var(--app-border); overflow-x:auto; }
.model-category-card { flex-shrink:0; gap:8px; min-height:38px; padding:0 12px; border-radius:6px; font-size:13px; color:var(--app-text-secondary); }
.category-count { min-width:20px; padding:1px 5px; border-radius:4px; background:var(--app-surface-muted); font-size:11px; font-variant-numeric:tabular-nums; }
.model-category-card.is-active .category-count { background:var(--app-surface); }
.model-config-section { display:flex; flex:0 1 auto; flex-direction:column; min-height:0; margin:0; }
.model-config-section > header { flex-shrink:0; }
.model-list-heading { display:flex; align-items:baseline; flex-wrap:wrap; gap:8px 14px; }
.model-list-count { font-size:12px; color:var(--app-text-secondary); }
.model-config-list { flex:1; min-height:0; max-height:none; }
.model-config-list :deep(table) { min-width:920px; }
.model-config-list :deep(th),.model-config-list :deep(td) { padding-block:14px; }
.model-config-list :deep(th[scope=row]) { min-width:250px; max-width:300px; }
.config-identity { display:flex; align-items:center; gap:12px; }
.config-identity > div { min-width:0; }
.config-name { display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.config-name strong { font-size:13px; font-weight:600; white-space:normal; overflow-wrap:anywhere; }
.config-identity code { display:block; margin-top:4px; max-width:200px; color:var(--app-text-secondary); font-size:11px; white-space:normal; overflow-wrap:anywhere; }
.config-identity small { display:block; margin-top:3px; color:var(--app-text-secondary); font-size:11px; }
.config-discount { color:var(--creation-warning); background:var(--app-warning-soft); border-radius:4px; padding:1px 5px; font-size:11px; }
.config-capabilities { display:grid; gap:6px; min-width:120px; max-width:200px; color:var(--app-text); font-size:12px; }
.config-capabilities small { font-size:11px; color:var(--app-text-secondary); }
.config-prices { display:grid; gap:4px; min-width:170px; margin:0; }
.config-prices > div { display:flex; align-items:baseline; justify-content:space-between; gap:12px; }
.config-prices dt { font-size:11px; color:var(--app-text-secondary); }
.config-prices dd { margin:0; }
.config-prices :deep(strong) { font-size:12px; font-weight:500; }
.config-actions { display:flex; justify-content:flex-end; align-items:center; gap:2px; }
.config-actions .config-delete { color:var(--app-text-secondary); }
.config-actions .config-delete:hover { color:var(--creation-danger); background:var(--app-danger-soft); }
.model-state,.model-empty-state { display:flex; flex:1; min-height:240px; align-items:center; justify-content:center; flex-direction:column; gap:12px; color:var(--app-text-secondary); }
.model-empty-state h3,.model-empty-state p { margin:0; }
.model-empty-state h3 { color:var(--app-text); }
.model-empty-state p { max-width:360px; text-align:center; font-size:12px; }
.model-modal-backdrop { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 16px; background: rgb(8 9 12 / 64%); backdrop-filter: blur(8px); }
.model-modal { display:grid; gap:24px; margin:0; padding:0; color:var(--app-text); background:transparent; }
.model-modal > header, .model-modal > footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.model-modal > header > div { display: flex; align-items: center; gap: 11px; }
.model-modal header small { color: var(--app-accent); font-size: 12px; font-weight: 750; letter-spacing: .14em; }
.model-modal h2 { margin: 3px 0 0; font-size: 17px; }
.model-modal header > button { display: grid; width: 34px; height: 34px; place-items: center; border: 0; border-radius: 8px; cursor: pointer; }
.model-form-grid { display: grid; grid-template-columns: minmax(0, 1fr) 180px; gap: 16px; }
.model-form-grid label { display: grid; gap: 7px; color: var(--app-text-secondary); font-size: 12px; }
.model-form-grid label.is-full { grid-column: 1 / -1; }
.model-form-grid label > span:first-child { font-weight: 600; }
.model-form-grid label > small { color: var(--app-text-muted); font-size: 12px; }
.model-form-grid input { width: 100%; min-height: 39px; padding: 0 11px; border: 1px solid var(--app-border); border-radius: 9px; outline: 0; color: var(--app-text); background: var(--app-surface-muted); caret-color: var(--app-text); font-size: 12px; transition: border-color .15s ease, background-color .15s ease, box-shadow .15s ease; }
.model-form-grid :deep(.app-select) { width: 100%; }
.model-form-grid :deep(.app-select__trigger) { min-height: 39px; padding: 0 11px; background: var(--app-surface-muted); font-size: 12px; }
.model-form-grid :deep(.app-select__trigger:hover) { background: var(--app-surface-hover); }
.model-form-grid :deep(.app-select.is-open .app-select__trigger) { background: var(--app-surface-hover); }
.model-readonly-value { display: flex; width: 100%; min-height: 39px; align-items: center; padding: 0 11px; border-radius: 9px; color: var(--app-text); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px var(--app-border); font-size: 12px; }
.model-form-grid input::placeholder { color: var(--app-text-muted); opacity: 1; }
.model-form-grid input:hover { border-color: var(--app-border-strong); }
.model-form-grid input:focus { border-color: var(--app-accent); color: var(--app-text); background: var(--app-surface-hover); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent); }
.model-form-grid input:-webkit-autofill,
.model-form-grid input:-webkit-autofill:hover,
.model-form-grid input:-webkit-autofill:focus { border-color: var(--app-border-strong); -webkit-text-fill-color: var(--app-text); caret-color: var(--app-text); box-shadow: 0 0 0 1000px var(--app-surface-muted) inset; }
.json-capability-field { display: flex !important; min-height: 64px; flex-direction: row; align-items: center; justify-content: space-between; gap: 16px !important; padding: 12px 14px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface-muted); }
.json-capability-copy { display: grid; gap: 4px; }
.json-capability-copy strong { color: var(--app-text); font-size: 12px; }
.json-capability-copy small { color: var(--app-text-muted); font-size: 12px; line-height: 1.5; }
.model-form-grid .json-capability-field > input { position: relative; width: 38px; min-width: 38px; height: 22px; min-height: 22px; margin: 0; padding: 0; border: 0; border-radius: 999px; appearance: none; background: var(--app-border-strong); cursor: pointer; transition: background .16s ease; }
.model-form-grid .json-capability-field > input::after { position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: var(--app-surface); box-shadow: 0 1px 4px rgb(0 0 0 / 24%); content: ''; transition: transform .16s ease; }
.model-form-grid .json-capability-field > input:checked { background: var(--app-accent); }
.model-form-grid .json-capability-field > input:checked::after { transform: translateX(16px); }
.model-form-grid .json-capability-field > input:focus-visible { outline: 3px solid color-mix(in srgb,var(--app-accent) 20%,transparent); outline-offset: 2px; box-shadow: none; }
.input-with-icon { position: relative; display: flex; align-items: center; }
.input-with-icon > svg { position: absolute; left: 11px; z-index: 1; color: var(--app-text-muted); }
.input-with-icon > input { padding-left: 34px; }
.secret-input > input { padding-right: 42px; }
.secret-input > button { position: absolute; right: 5px; display: grid; width: 32px; height: 30px; place-items: center; border: 0; border-radius: 7px; color: var(--app-text-muted); background: transparent; cursor: pointer; }
.secret-input > button:hover { color: var(--app-accent); background: var(--app-accent-soft); }
.model-modal > footer { justify-content: flex-end; padding-top: 3px; }
.model-modal-hint { margin-right: auto; color: var(--app-text-muted); font-size: 12px; }
.model-modal > footer .app-button { min-height: 38px; padding: 0 14px; border-radius: 9px; cursor: pointer; font-size: 12px; }
.model-modal > footer button:disabled { cursor: not-allowed; opacity: .55; }
.pricing-editor { display: grid; gap: 10px; margin-top: 2px; padding: 14px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface-muted); }
.pricing-sub { display: grid; gap: 8px; margin-top: 4px; padding-top: 10px; border-top: 1px dashed var(--app-border); }
.pricing-title { color: var(--app-text-secondary); font-size: 12px; font-weight: 600; }
.pricing-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.pricing-grid label { display: grid; gap: 6px; color: var(--app-text-muted); font-size: 12px; }
.pricing-grid input { width: 100%; min-height: 36px; padding: 0 10px; border: 1px solid var(--app-border); border-radius: 8px; outline: 0; color: var(--app-text); background: var(--app-surface); font-size: 12px; }
.pricing-grid input:focus { border-color: var(--app-accent); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 10%,transparent); }
@media(max-width:767px) {
 .model-settings-page { height:auto; }
 .model-config-list { flex:none; max-height:65dvh; }
 .model-category-card { min-height:44px; }
 .model-form-grid { grid-template-columns:1fr; }
 .model-form-grid label,.model-form-grid label.is-full { grid-column:1; }
}
.enhancement-resolution-options{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0}.enhancement-resolution-options label{display:flex;gap:6px;align-items:center}.enhancement-resolution-options input{width:auto;min-height:auto}
</style>
