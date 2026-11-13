export type ImageApiProtocol = 'novelvids' | 'openai_compatible' | 'openrouter_compatible' | 'volcengine_ark' | 'minimax' | 'autodl' | 'dashscope' | 'volcengine_mediakit' | 'volcengine_openspeech'

export type ImageModelType = 'seedream_5_lite' | 'seedream_5_pro' | 'seedream_5_flash' | 'gpt_image_2' | 'gpt_image_2_5' | 'gpt_image_2_6' | 'gpt_image_2_6_sunburst' | 'gpt_image_2_6_flare'

export type VideoGenerationModelType = 'seedance_2' | 'seedance_2_fast' | 'seedance_2_mini' | 'seedance_2_5' | 'minimax_h3' | 'minimax_h3_autodl' | 'wan_3'

export interface ModelPricing {
  type: 'text' | 'image' | 'video' | 'media_processing' | 'asr'
  currency: string
  input_price_per_1m?: number
  cache_input_price_per_1m?: number
  output_price_per_1m?: number
  price_per_minute?: number
  prices?: Record<string, number>
  input_image?: { first_free: number; price_per_image: number }
  video_reference_prices?: Record<string, number>
  billing_unit?: 'token' | 'second' | 'minute'
  tiers?: Array<{ short_side_max: number; fps_max: number; price: number }>
  discount?: number
  discount_description?: string
}

export interface GenerationCapabilities {
  text_pricing?: Record<string, ModelPricing>
  audio_recognition?: { base_url: string; model: string; api_protocol: ImageApiProtocol; pricing: ModelPricing }
  media_processing?: { base_url: string; model: string; api_protocol: ImageApiProtocol; processing_options: Record<string, unknown>; pricing: ModelPricing; resolutions?: Array<{ value: string; short_side: number }> }
  image: Record<string, string[]>
  image_protocols?: Partial<Record<ImageModelType, ImageApiProtocol[]>>
  video: Record<string, string[]>
  video_protocols?: Partial<Record<VideoGenerationModelType, Array<{ value: ImageApiProtocol; label: string; resolutions: string[] }>>>
  video_pricing?: Partial<Record<VideoGenerationModelType, ModelPricing>>
}

export interface AiModelConfig { id: number; task_type: number; task_types?: number[]; name: string; base_url?: string; api_key?: string; model?: string; api_protocol: ImageApiProtocol; image_model_type?: ImageModelType | null; video_model_type?: VideoGenerationModelType | null; is_active: boolean; concurrency: number; supports_json_output: boolean; supports_tool_calls?: boolean; max_context_characters?: number | null; thinking?: 'enabled' | 'disabled' | null; max_tokens?: number | null; pricing?: ModelPricing | null; processing_options?: Record<string, unknown> | null; scope?: 'official' | 'studio_platform'; created_at: string; updated_at: string }

export interface GeneralConfig { id: number; prompt_language: 'zh' | 'en'; created_at: string; updated_at: string }

export interface EnumItem { value: number; label: string }

export interface ConfigEnumItem { value: string | number; label: string; name?: string }

export interface AllEnums {
  task_status: EnumItem[]
  asset_type: EnumItem[]
  image_source: EnumItem[]
  workflow_status: EnumItem[]
  ai_task_type: EnumItem[]
  video_model_type: ConfigEnumItem[]
  image_model_type: ConfigEnumItem[]
  [key: string]: ConfigEnumItem[]
}

export interface PaginationResponse<T> {
  code: number
  message: string
  data: {
    items: T[]
    pagination: { total: number; page: number; page_size: number; pages: number }
  }
}

export interface SingleResponse<T> { code: number; message: string; data: T }

export interface AuthUser {
  id: number
  username: string
  nickname: string
  avatar_url: string
  is_super_admin: boolean
  created_at?: string
}

export interface AuthStatus {
  legacy_works_enabled?: boolean
  deployment_role?: 'studio' | 'platform'
  enabled: boolean
  provider?: 'password' | 'qiling'
  qiling_enabled?: boolean
  legal_ready?: boolean
  legal_missing?: string[]
}

export interface LoginResult { token: string; user: AuthUser }

export interface QilingAttempt { attempt: string; authorization_url: string; expires_in: number }

export type QilingPoll = { status: 'completed'; session: LoginResult } | { status: 'pending' | 'expired' | 'failed' | 'bound' }

export interface BillingSummary {
  total_cost: number
  total_records: number
  platform_cost?: string
  local_charge?: string
  pending_records?: number
  by_billing_type: Array<{ billing_type: string; cost: number }>
  by_task_type: Array<{ task_type: number; cost: number }>
  by_model: Array<{ model: string; cost: number; record_count?: number }>
  daily_trend: Array<{ date: string; cost: number }>
}
export interface AuthMe { user: AuthUser; balance: string; total_cost: number; is_super_admin: boolean; qiling_bound: boolean }
