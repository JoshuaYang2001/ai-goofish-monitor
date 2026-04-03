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

export interface ItemSearchResult {
  item_id: string
  '商品标题': string
  '当前售价': string
  '商品链接': string
  '想要人数': string
  '浏览量': string
  '卖家 ID': string
  '卖家昵称': string
  '芝麻信用': string
  '商品图片列表': string[]
}

export interface SearchHistoryItem {
  search_type: string
  search_value: string
  result_json: ItemSearchResult | null
  searched_at: string
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
