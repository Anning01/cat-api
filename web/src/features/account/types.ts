export interface AccountRow {
  id: number; username?: string; nickname?: string; user_name?: string; user_id?: number; account_user_id?: number
  balance?: string; total_cost?: string; created_at: string; status?: number | string; is_super_admin?: boolean
  avatar_url?: string; qiling_bound?: boolean; active_key_count?: number; last_seen_at?: string
  out_trade_no?: string; amount?: string; paid_at?: string; expires_at?: string; refunded_at?: string
  transaction_id?: string; refund_id?: string; refund_reason?: string; payment_method?: string
  billing_type?: string; cost?: string; balance_after?: string; usage?: Record<string, unknown>; usage_record_id?: number
  change_amount?: string; type?: string; operator_user_id?: number; operator_name?: string; action?: string; note?: string
}
export interface AccountTable {
  items: AccountRow[]
  pagination: { total: number; page: number; page_size: number; pages: number }
  summary?: { total_cost: string; total_transactions: number }
  snapshot_id?: number
}
