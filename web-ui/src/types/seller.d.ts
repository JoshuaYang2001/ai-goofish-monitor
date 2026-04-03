export interface SellerInfo {
  seller_id: string
  seller_nickname: string
  seller_avatar: string
  zhima_credit: string
  registration_days: number
  good_rate: string
  total_items: number
  total_ratings: number
  last_updated: string
}

export interface SellerListResponse {
  seller_id: string
  list_type: 'blacklist' | 'whitelist'
  reason: string
  created_at: string
  expires_at: string | null
}

export interface MetricsSnapshot {
  price: number | null
  price_display: string | null
  want_count: number | null
  browse_count: number | null
  snapshot_time: string
}

export interface PriceHistoryPoint {
  time: string
  price: number | null
  price_display: string | null
}

export interface WantCountHistoryPoint {
  time: string
  want_count: number | null
}
