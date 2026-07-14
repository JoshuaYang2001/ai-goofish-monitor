<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowDownRight, ArrowUpRight, Clock3, RefreshCw, Search, TrendingUp } from 'lucide-vue-next'
import { getMetricChanges } from '@/api/metrics'
import type { MetricChangeItem, MetricChangesResponse } from '@/types/metrics.d.ts'
import { useToast } from '@/components/ui/toast/use-toast'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const DEFAULT_INTERVALS = [1, 3, 6, 12, 24, 48, 72]
const ALL_TASKS = '__all__'
const { toast } = useToast()

const intervals = ref([...DEFAULT_INTERVALS])
const selectedInterval = ref(24)
const customInterval = ref<number>()
const selectedTask = ref(ALL_TASKS)
const searchText = ref('')
const data = ref<MetricChangesResponse | null>(null)
const isLoading = ref(false)

const selectedSummary = computed(() => data.value?.summaries[String(selectedInterval.value)] ?? null)
const sortedItems = computed(() => {
  const rows = [...(data.value?.items ?? [])]
  return rows.sort((left, right) => {
    const rightChange = right.changes[String(selectedInterval.value)]?.want_change ?? 0
    const leftChange = left.changes[String(selectedInterval.value)]?.want_change ?? 0
    return rightChange - leftChange
  })
})

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
  return item.changes[String(selectedInterval.value)]
}

async function loadChanges() {
  isLoading.value = true
  try {
    data.value = await getMetricChanges(
      intervals.value,
      selectedTask.value === ALL_TASKS ? undefined : selectedTask.value,
      searchText.value.trim() || undefined,
    )
  } catch (error: unknown) {
    toast({
      title: '加载变化数据失败',
      description: error instanceof Error ? error.message : '请稍后重试',
      variant: 'destructive',
    })
  } finally {
    isLoading.value = false
  }
}

async function addCustomInterval() {
  const hours = Number(customInterval.value)
  if (!Number.isInteger(hours) || hours < 1 || hours > 720) {
    toast({ title: '请输入 1 到 720 之间的整数小时', variant: 'destructive' })
    return
  }
  if (!intervals.value.includes(hours)) {
    if (intervals.value.length >= 8) {
      toast({ title: '最多同时查看 8 个时间间隔', variant: 'destructive' })
      return
    }
    intervals.value = [...intervals.value, hours].sort((left, right) => left - right)
  }
  selectedInterval.value = hours
  customInterval.value = undefined
  await loadChanges()
}

onMounted(loadChanges)
</script>

<template>
  <div class="space-y-6">
    <header class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <div class="mb-2 flex items-center gap-2 text-sm font-semibold text-primary">
          <TrendingUp class="h-4 w-4" />
          商品指标历史
        </div>
        <h1 class="text-2xl font-bold text-slate-900">价格与想要数变化</h1>
        <p class="mt-1 text-sm text-slate-500">按时间窗口对比当前快照与历史基线，数据仅来自当前租户。</p>
      </div>
      <Button variant="outline" :disabled="isLoading" @click="loadChanges">
        <RefreshCw class="mr-2 h-4 w-4" :class="isLoading ? 'animate-spin' : ''" />
        刷新数据
      </Button>
    </header>

    <Card>
      <CardContent class="grid gap-4 p-5 lg:grid-cols-[minmax(0,1fr)_240px_360px] lg:items-end">
        <div class="space-y-2">
          <Label for="metric-search">搜索商品</Label>
          <div class="relative">
            <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              id="metric-search"
              v-model="searchText"
              class="pl-9"
              placeholder="商品标题或商品 ID"
              @keyup.enter="loadChanges"
            />
          </div>
        </div>
        <div class="space-y-2">
          <Label>监控任务</Label>
          <Select v-model="selectedTask" @update:model-value="loadChanges">
            <SelectTrigger><SelectValue placeholder="全部任务" /></SelectTrigger>
            <SelectContent>
              <SelectItem :value="ALL_TASKS">全部任务</SelectItem>
              <SelectItem v-for="taskName in data?.task_names ?? []" :key="taskName" :value="taskName">
                {{ taskName }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="space-y-2">
          <Label for="custom-hours">自定义时间间隔</Label>
          <div class="flex gap-2">
            <Input id="custom-hours" v-model.number="customInterval" type="number" min="1" max="720" placeholder="小时（1-720）" />
            <Button @click="addCustomInterval">添加</Button>
            <Button variant="secondary" @click="loadChanges">查询</Button>
          </div>
        </div>
      </CardContent>
    </Card>

    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <button
        v-for="hours in intervals"
        :key="hours"
        type="button"
        class="rounded-xl border bg-white p-4 text-left transition hover:border-primary/50 hover:shadow-sm"
        :class="selectedInterval === hours ? 'border-primary ring-2 ring-primary/10' : 'border-slate-200'"
        @click="selectedInterval = hours"
      >
        <div class="flex items-center justify-between">
          <span class="flex items-center gap-2 text-sm font-bold text-slate-700"><Clock3 class="h-4 w-4" />近 {{ hours }} 小时</span>
          <span class="text-xs text-slate-400">{{ data?.summaries[String(hours)]?.tracked_items ?? 0 }} 件</span>
        </div>
        <div class="mt-4 grid grid-cols-2 gap-3">
          <div>
            <p class="text-xs text-slate-400">想要数变化</p>
            <p class="mt-1 text-xl font-black" :class="changeClass(data?.summaries[String(hours)]?.want_change)">
              {{ signed(data?.summaries[String(hours)]?.want_change) }}
            </p>
          </div>
          <div>
            <p class="text-xs text-slate-400">价格总变化</p>
            <p class="mt-1 text-xl font-black" :class="changeClass(data?.summaries[String(hours)]?.price_change)">
              {{ signed(data?.summaries[String(hours)]?.price_change, '¥') }}
            </p>
          </div>
        </div>
      </button>
    </div>

    <div class="grid gap-4 md:grid-cols-3">
      <Card>
        <CardHeader class="pb-2"><CardTitle class="text-sm text-slate-500">当前窗口</CardTitle></CardHeader>
        <CardContent><p class="text-3xl font-black">{{ selectedInterval }} 小时</p></CardContent>
      </Card>
      <Card>
        <CardHeader class="pb-2"><CardTitle class="text-sm text-slate-500">想要数发生变化</CardTitle></CardHeader>
        <CardContent><p class="text-3xl font-black text-emerald-600">{{ selectedSummary?.want_changed_items ?? 0 }} 件</p></CardContent>
      </Card>
      <Card>
        <CardHeader class="pb-2"><CardTitle class="text-sm text-slate-500">价格发生变化</CardTitle></CardHeader>
        <CardContent><p class="text-3xl font-black text-indigo-600">{{ selectedSummary?.price_changed_items ?? 0 }} 件</p></CardContent>
      </Card>
    </div>

    <Card class="overflow-hidden">
      <CardHeader class="border-b bg-slate-50/60">
        <CardTitle class="text-base">近 {{ selectedInterval }} 小时商品明细</CardTitle>
      </CardHeader>
      <CardContent class="p-0">
        <div class="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead class="min-w-[280px]">商品</TableHead>
                <TableHead>监控任务</TableHead>
                <TableHead>当前想要数</TableHead>
                <TableHead>想要数变化</TableHead>
                <TableHead>当前价格</TableHead>
                <TableHead>价格变化</TableHead>
                <TableHead class="min-w-[170px]">更新时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="item in sortedItems" :key="item.item_id">
                <TableCell>
                  <a v-if="item.link" :href="item.link" target="_blank" rel="noreferrer" class="font-semibold text-slate-800 hover:text-primary">
                    {{ item.title || item.item_id }}
                  </a>
                  <p v-else class="font-semibold text-slate-800">{{ item.title || item.item_id }}</p>
                  <p class="mt-1 text-xs text-slate-400">ID: {{ item.item_id }}</p>
                </TableCell>
                <TableCell>{{ item.task_name || '-' }}</TableCell>
                <TableCell class="font-semibold">{{ formatNumber(item.want_count) }}</TableCell>
                <TableCell :class="changeClass(currentChange(item)?.want_change)">
                  <span class="inline-flex items-center gap-1 font-bold">
                    <ArrowUpRight v-if="(currentChange(item)?.want_change ?? 0) > 0" class="h-4 w-4" />
                    <ArrowDownRight v-else-if="(currentChange(item)?.want_change ?? 0) < 0" class="h-4 w-4" />
                    {{ signed(currentChange(item)?.want_change) }}
                  </span>
                </TableCell>
                <TableCell class="font-semibold">{{ item.price_display || (item.price === null ? '-' : `¥${formatNumber(item.price)}`) }}</TableCell>
                <TableCell class="font-bold" :class="changeClass(currentChange(item)?.price_change)">
                  {{ signed(currentChange(item)?.price_change, '¥') }}
                </TableCell>
                <TableCell class="text-slate-500">{{ formatDate(item.snapshot_time) }}</TableCell>
              </TableRow>
              <TableRow v-if="!isLoading && sortedItems.length === 0">
                <TableCell colspan="7" class="h-32 text-center text-slate-500">暂无指标历史，运行监控任务后会自动记录。</TableCell>
              </TableRow>
              <TableRow v-if="isLoading">
                <TableCell colspan="7" class="h-32 text-center text-slate-500">正在加载变化数据...</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
