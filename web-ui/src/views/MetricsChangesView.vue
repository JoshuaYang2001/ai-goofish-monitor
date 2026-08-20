<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Clock3, ListTree, RefreshCw, Search, TrendingUp, X } from 'lucide-vue-next'
import { getMetricChanges } from '@/api/metrics'
import { getAllTasks } from '@/api/tasks'
import type { MetricChangesResponse, MetricIntervalChange, MetricTaskGroup } from '@/types/metrics.d.ts'
import type { Task } from '@/types/task.d.ts'
import { useWebSocket } from '@/composables/useWebSocket'
import { useToast } from '@/components/ui/toast/use-toast'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import MetricTaskSection from '@/components/metrics/MetricTaskSection.vue'

const DEFAULT_INTERVALS = [1, 3, 6, 12, 24, 48, 72]
const { toast } = useToast()
const { on } = useWebSocket()

const intervals = ref([...DEFAULT_INTERVALS])
const selectedInterval = ref(24)
const customInterval = ref<number>()
const tasks = ref<Task[]>([])
const searchText = ref('')
const data = ref<MetricChangesResponse | null>(null)
const isLoading = ref(false)

const selectedSummary = computed(() => data.value?.summaries[String(selectedInterval.value)] ?? null)
const taskGroups = computed<MetricTaskGroup[]>(() => {
  const itemsByTask = new Map<string, MetricChangesResponse['items']>()
  for (const item of data.value?.items ?? []) {
    const taskItems = itemsByTask.get(item.task_name) ?? []
    taskItems.push(item)
    itemsByTask.set(item.task_name, taskItems)
  }

  const visibleTasks = searchText.value.trim()
    ? tasks.value.filter((task) => itemsByTask.has(task.task_name))
    : tasks.value

  return visibleTasks.map((task) => {
    const taskName = task.task_name
    const items = [...(itemsByTask.get(taskName) ?? [])].sort((left, right) => {
      const rightChange = right.changes[String(selectedInterval.value)]?.want_change ?? 0
      const leftChange = left.changes[String(selectedInterval.value)]?.want_change ?? 0
      return rightChange - leftChange
    })
    const availableChanges = items
      .map((item) => item.changes[String(selectedInterval.value)])
      .filter((change): change is MetricIntervalChange => Boolean(change?.available))
    const latestSnapshotTime = items.reduce<string | null>((latest, item) => {
      if (!latest || item.snapshot_time > latest) return item.snapshot_time
      return latest
    }, null)

    return {
      key: String(task.id),
      taskName,
      task,
      items,
      trackedItems: items.length,
      availableItems: availableChanges.length,
      wantChange: availableChanges.length
        ? availableChanges.reduce((total, change) => total + (change.want_change ?? 0), 0)
        : null,
      priceChange: availableChanges.length
        ? availableChanges.reduce((total, change) => total + (change.price_change ?? 0), 0)
        : null,
      wantChangedItems: availableChanges.filter((change) => (change.want_change ?? 0) !== 0).length,
      priceChangedItems: availableChanges.filter((change) => (change.price_change ?? 0) !== 0).length,
      latestSnapshotTime,
    }
  })
})

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
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

function summaryChange(hours: number, field: 'want_change' | 'price_change') {
  const summary = data.value?.summaries[String(hours)]
  if (!summary || summary.available_items === 0) return null
  return summary[field]
}

async function loadChanges() {
  isLoading.value = true
  try {
    data.value = await getMetricChanges(
      intervals.value,
      undefined,
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

async function loadTasksAndChanges() {
  isLoading.value = true
  try {
    const loadedTasks = await getAllTasks()
    tasks.value = loadedTasks
    await loadChanges()
  } catch (error: unknown) {
    toast({
      title: '加载监控任务失败',
      description: error instanceof Error ? error.message : '请稍后重试',
      variant: 'destructive',
    })
  } finally {
    isLoading.value = false
  }
}

async function clearSearch() {
  searchText.value = ''
  await loadChanges()
}

function scrollToTask(group: MetricTaskGroup) {
  document.getElementById(`metric-task-${group.key}`)?.scrollIntoView({
    behavior: 'smooth',
    block: 'start',
  })
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

on('tasks_updated', loadTasksAndChanges)
on('task_completed', loadChanges)
on('task_failed', loadChanges)
onMounted(loadTasksAndChanges)
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
        <p class="mt-1 text-sm text-slate-500">全部监控任务集中展示，无需逐个选择即可查看变化和商品明细。</p>
      </div>
      <Button variant="outline" :disabled="isLoading" @click="loadTasksAndChanges">
        <RefreshCw class="mr-2 h-4 w-4" :class="isLoading ? 'animate-spin' : ''" />
        刷新数据
      </Button>
    </header>

    <Card>
      <CardContent class="grid gap-4 p-5 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
        <div class="space-y-2">
          <Label for="metric-search">搜索全部任务中的商品</Label>
          <div class="relative">
            <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              id="metric-search"
              v-model="searchText"
              class="pl-9 pr-10"
              placeholder="商品标题、商品 ID 或任务名称"
              @keyup.enter="loadChanges"
            />
            <button
              v-if="searchText"
              type="button"
              class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition hover:text-slate-700"
              aria-label="清空搜索"
              @click="clearSearch"
            >
              <X class="h-4 w-4" />
            </button>
          </div>
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

    <Card v-if="taskGroups.length">
      <CardHeader class="pb-3">
        <div class="flex items-center justify-between gap-4">
          <div>
            <CardTitle class="flex items-center gap-2 text-base">
              <ListTree class="h-4 w-4 text-primary" />
              监控任务概览
            </CardTitle>
            <p class="mt-1 text-xs text-slate-500">所有任务均已铺开，点击卡片可快速定位到对应商品明细。</p>
          </div>
          <span class="shrink-0 text-sm font-semibold text-slate-500">{{ taskGroups.length }} 个任务</span>
        </div>
      </CardHeader>
      <CardContent class="grid gap-3 pt-0 sm:grid-cols-2 xl:grid-cols-3">
        <button
          v-for="group in taskGroups"
          :key="group.key"
          type="button"
          class="rounded-lg border border-slate-200 bg-slate-50/60 p-3.5 text-left transition hover:border-primary/40 hover:bg-primary/[0.03] hover:shadow-sm"
          @click="scrollToTask(group)"
        >
          <div class="flex items-start justify-between gap-3">
            <p class="line-clamp-2 font-semibold text-slate-800">{{ group.taskName }}</p>
            <span class="shrink-0 rounded-full bg-white px-2 py-0.5 text-xs text-slate-500 shadow-sm">
              {{ group.availableItems }}/{{ group.trackedItems }} 有效
            </span>
          </div>
          <div class="mt-3 flex items-center gap-5 text-xs">
            <span class="text-slate-500">想要数 <strong :class="changeClass(group.wantChange)">{{ signed(group.wantChange) }}</strong></span>
            <span class="text-slate-500">价格 <strong :class="changeClass(group.priceChange)">{{ signed(group.priceChange, '¥') }}</strong></span>
          </div>
        </button>
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
          <span class="text-xs text-slate-400">
            {{ data?.summaries[String(hours)]?.available_items ?? 0 }}/{{ data?.summaries[String(hours)]?.tracked_items ?? 0 }} 件有效
          </span>
        </div>
        <div class="mt-4 grid grid-cols-2 gap-3">
          <div>
            <p class="text-xs text-slate-400">想要数变化</p>
            <p class="mt-1 text-xl font-black" :class="changeClass(summaryChange(hours, 'want_change'))">
              {{ signed(summaryChange(hours, 'want_change')) }}
            </p>
          </div>
          <div>
            <p class="text-xs text-slate-400">价格总变化</p>
            <p class="mt-1 text-xl font-black" :class="changeClass(summaryChange(hours, 'price_change'))">
              {{ signed(summaryChange(hours, 'price_change'), '¥') }}
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
        <CardContent>
          <p class="text-3xl font-black text-emerald-600">
            {{ selectedSummary && selectedSummary.available_items > 0 ? `${selectedSummary.want_changed_items} 件` : '-' }}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader class="pb-2"><CardTitle class="text-sm text-slate-500">价格发生变化</CardTitle></CardHeader>
        <CardContent>
          <p class="text-3xl font-black text-indigo-600">
            {{ selectedSummary && selectedSummary.available_items > 0 ? `${selectedSummary.price_changed_items} 件` : '-' }}
          </p>
        </CardContent>
      </Card>
    </div>

    <section class="space-y-4">
      <div class="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 class="text-lg font-bold text-slate-900">各任务商品明细</h2>
          <p class="mt-1 text-sm text-slate-500">以下任务默认全部展开，当前展示近 {{ selectedInterval }} 小时的变化。</p>
        </div>
        <p v-if="taskGroups.length" class="text-sm text-slate-500">共 {{ taskGroups.length }} 个任务</p>
      </div>

      <div v-if="isLoading && !data" class="flex h-40 items-center justify-center rounded-xl border bg-white text-sm text-slate-500">
        正在加载全部任务的变化数据...
      </div>
      <div v-else-if="taskGroups.length" class="space-y-5">
        <MetricTaskSection
          v-for="group in taskGroups"
          :key="group.key"
          :group="group"
          :selected-interval="selectedInterval"
        />
      </div>
      <div v-else class="flex h-40 items-center justify-center rounded-xl border bg-white px-6 text-center text-sm text-slate-500">
        {{ searchText.trim() ? '没有找到匹配的商品或监控任务。' : '暂无监控任务，创建并成功运行任务后会显示在这里。' }}
      </div>
    </section>
  </div>
</template>
