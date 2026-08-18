<script setup lang="ts">
import { ArrowDownRight, ArrowUpRight, Clock3, ExternalLink } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { MetricChangeItem, MetricTaskGroup } from '@/types/metrics.d.ts'

const props = defineProps<{
  group: MetricTaskGroup
  selectedInterval: number
}>()

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
}

function formatDate(value: string | null | undefined) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function changeClass(value: number | null | undefined) {
  if (!value) return 'text-slate-500'
  return value > 0 ? 'text-emerald-600' : 'text-rose-600'
}

function signed(value: number | null | undefined, prefix = '') {
  if (value === null || value === undefined) return '-'
  const sign = value > 0 ? '+' : ''
  return `${sign}${prefix}${formatNumber(value)}`
}

function currentChange(item: MetricChangeItem) {
  return item.changes[String(props.selectedInterval)]
}

function taskStatus() {
  if (!props.group.task) return { label: '历史任务', className: 'border-slate-200 bg-slate-50 text-slate-600' }
  if (props.group.task.is_running) return { label: '运行中', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' }
  if (props.group.task.is_queued) return { label: '排队中', className: 'border-amber-200 bg-amber-50 text-amber-700' }
  if (props.group.task.is_paused) return { label: '已暂停', className: 'border-slate-200 bg-slate-100 text-slate-600' }
  if (!props.group.task.enabled) return { label: '未启用', className: 'border-slate-200 bg-slate-50 text-slate-500' }
  return { label: '监控中', className: 'border-blue-200 bg-blue-50 text-blue-700' }
}
</script>

<template>
  <Card :id="`metric-task-${group.key}`" class="scroll-mt-24 overflow-hidden">
    <CardHeader class="border-b bg-slate-50/70 pb-4">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <CardTitle class="truncate text-base text-slate-900">{{ group.taskName }}</CardTitle>
            <Badge variant="outline" :class="taskStatus().className">{{ taskStatus().label }}</Badge>
          </div>
          <p class="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
            <Clock3 class="h-3.5 w-3.5" />
            最后更新：{{ formatDate(group.latestSnapshotTime) }}
          </p>
        </div>

        <div class="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
          <div>
            <p class="text-xs text-slate-400">有效商品</p>
            <p class="mt-1 font-bold text-slate-800">{{ group.availableItems }}/{{ group.trackedItems }} 件</p>
          </div>
          <div>
            <p class="text-xs text-slate-400">想要数变化</p>
            <p class="mt-1 font-bold" :class="changeClass(group.wantChange)">{{ signed(group.wantChange) }}</p>
          </div>
          <div>
            <p class="text-xs text-slate-400">价格总变化</p>
            <p class="mt-1 font-bold" :class="changeClass(group.priceChange)">{{ signed(group.priceChange, '¥') }}</p>
          </div>
          <div>
            <p class="text-xs text-slate-400">发生变化</p>
            <p class="mt-1 font-bold text-slate-800">{{ group.wantChangedItems + group.priceChangedItems }} 项</p>
          </div>
        </div>
      </div>
    </CardHeader>

    <CardContent class="p-0">
      <div v-if="group.items.length" class="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="min-w-[280px]">商品</TableHead>
              <TableHead>当前想要数</TableHead>
              <TableHead>想要数变化</TableHead>
              <TableHead>当前价格</TableHead>
              <TableHead>价格变化</TableHead>
              <TableHead class="min-w-[170px]">更新时间</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="item in group.items" :key="item.item_id">
              <TableCell>
                <a
                  v-if="item.link"
                  :href="item.link"
                  target="_blank"
                  rel="noreferrer"
                  class="group/link inline-flex max-w-[420px] items-start gap-1.5 font-semibold text-slate-800 hover:text-primary"
                >
                  <span>{{ item.title || item.item_id }}</span>
                  <ExternalLink class="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-0 transition group-hover/link:opacity-100" />
                </a>
                <p v-else class="max-w-[420px] font-semibold text-slate-800">{{ item.title || item.item_id }}</p>
                <p class="mt-1 text-xs text-slate-400">ID: {{ item.item_id }}</p>
              </TableCell>
              <TableCell class="font-semibold">{{ formatNumber(item.want_count) }}</TableCell>
              <TableCell :class="changeClass(currentChange(item)?.want_change)">
                <span class="inline-flex items-center gap-1 font-bold">
                  <ArrowUpRight v-if="(currentChange(item)?.want_change ?? 0) > 0" class="h-4 w-4" />
                  <ArrowDownRight v-else-if="(currentChange(item)?.want_change ?? 0) < 0" class="h-4 w-4" />
                  {{ signed(currentChange(item)?.want_change) }}
                </span>
              </TableCell>
              <TableCell class="font-semibold">
                {{ item.price_display || (item.price === null ? '-' : `¥${formatNumber(item.price)}`) }}
              </TableCell>
              <TableCell class="font-bold" :class="changeClass(currentChange(item)?.price_change)">
                {{ signed(currentChange(item)?.price_change, '¥') }}
              </TableCell>
              <TableCell class="text-slate-500">{{ formatDate(item.snapshot_time) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
      <div v-else class="flex h-28 items-center justify-center px-6 text-center text-sm text-slate-500">
        该任务暂无指标历史，成功运行监控后会自动显示在这里。
      </div>
    </CardContent>
  </Card>
</template>
