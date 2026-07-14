import { http } from '@/lib/http'
import type { MetricChangesResponse } from '@/types/metrics.d.ts'

export async function getMetricChanges(
  intervals: number[],
  taskName: string,
  search?: string,
): Promise<MetricChangesResponse> {
  const params = new URLSearchParams()
  intervals.forEach((hours) => params.append('interval', String(hours)))
  params.set('task_name', taskName)
  if (search) params.set('search', search)
  return await http(`/api/metrics/changes?${params.toString()}`)
}
