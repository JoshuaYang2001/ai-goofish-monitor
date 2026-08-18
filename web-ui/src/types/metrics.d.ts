import type { Task } from './task.d.ts'

export interface MetricIntervalChange {
  hours: number
  available: boolean
  baseline_time: string | null
  baseline_price: number | null
  baseline_want_count: number | null
  price_change: number | null
  want_change: number | null
}

export interface MetricChangeItem {
  item_id: string
  task_name: string
  title: string
  link: string | null
  seller_id: string | null
  snapshot_time: string
  price: number | null
  price_display: string | null
  want_count: number | null
  browse_count: number | null
  changes: Record<string, MetricIntervalChange>
}

export interface MetricChangeSummary {
  hours: number
  want_change: number
  price_change: number
  want_changed_items: number
  price_changed_items: number
  available_items: number
  tracked_items: number
}

export interface MetricChangesResponse {
  generated_at: string
  interval_hours: number[]
  task_names: string[]
  summaries: Record<string, MetricChangeSummary>
  items: MetricChangeItem[]
}

export interface MetricTaskGroup {
  key: string
  taskName: string
  task: Task | null
  items: MetricChangeItem[]
  trackedItems: number
  availableItems: number
  wantChange: number | null
  priceChange: number | null
  wantChangedItems: number
  priceChangedItems: number
  latestSnapshotTime: string | null
}
