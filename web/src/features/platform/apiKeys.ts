export interface ApiKeyRow {
  id: number
  name: string
  preview: string
  created_at: string
  allowed_model_ids?: string[] | null
  expires_at?: string | null
  is_expired?: boolean
  can_reveal?: boolean
}

export interface CreatedApiKey extends ApiKeyRow { key: string }
