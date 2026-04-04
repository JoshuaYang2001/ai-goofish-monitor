<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

interface TrendPoint {
  day: string
  run_id: string
  snapshot_time: string
  avg_price: number | null
  median_price: number | null
  avg_want_count: number | null
}

const props = defineProps<{
  points: TrendPoint[]
}>()
const { t } = useI18n()

// Mock 数据开关（测试完成后设为 false）
const useMockData = ref(false)

const mockPoints: TrendPoint[] = [
  { day: '2026-04-05', run_id: 'run_1', snapshot_time: '2026-04-05T10:00:00', avg_price: 150, median_price: 145, avg_want_count: 120 },
  { day: '2026-04-05', run_id: 'run_2', snapshot_time: '2026-04-05T12:00:00', avg_price: 148, median_price: 143, avg_want_count: 135 },
  { day: '2026-04-05', run_id: 'run_3', snapshot_time: '2026-04-05T14:00:00', avg_price: 155, median_price: 150, avg_want_count: 142 },
  { day: '2026-04-05', run_id: 'run_4', snapshot_time: '2026-04-05T16:00:00', avg_price: 152, median_price: 148, avg_want_count: 158 },
  { day: '2026-04-05', run_id: 'run_5', snapshot_time: '2026-04-05T18:00:00', avg_price: 145, median_price: 140, avg_want_count: 175 },
  { day: '2026-04-05', run_id: 'run_6', snapshot_time: '2026-04-05T20:00:00', avg_price: 142, median_price: 138, avg_want_count: 189 },
  { day: '2026-04-05', run_id: 'run_7', snapshot_time: '2026-04-05T22:00:00', avg_price: 138, median_price: 135, avg_want_count: 210 },
]

const chartWidth = 720
const chartHeight = 220
const padding = 24

const validPoints = computed(() => {
  // Mock 测试模式：直接使用 mock 数据
  if (useMockData.value) {
    return mockPoints.filter((point) => point.avg_price !== null && point.avg_price !== undefined)
  }
  return props.points.filter((point) => point.avg_price !== null && point.avg_price !== undefined)
})

const hasWantCountData = computed(() =>
  validPoints.value.some((point) => point.avg_want_count !== null && point.avg_want_count !== undefined)
)

// 价格范围（左 Y 轴）
const priceRange = computed(() => {
  const values = validPoints.value
    .map((point) => point.avg_price)
    .filter((value): value is number => typeof value === 'number')
  if (values.length === 0) {
    return { min: 0, max: 1 }
  }
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min === max) {
    return { min: min - 1, max: max + 1 }
  }
  return { min, max }
})

// 想要数范围（右 Y 轴）
const wantCountRange = computed(() => {
  const values = validPoints.value
    .map((point) => point.avg_want_count)
    .filter((value): value is number => typeof value === 'number')
  if (values.length === 0) {
    return { min: 0, max: 1 }
  }
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min === max) {
    return { min: 0, max: max + 1 }
  }
  return { min, max }
})

function resolveX(index: number) {
  if (validPoints.value.length <= 1) return chartWidth / 2
  const usableWidth = chartWidth - padding * 2
  return padding + (usableWidth / (validPoints.value.length - 1)) * index
}

function resolveYPrice(value: number) {
  const usableHeight = chartHeight - padding * 2
  const ratio = (value - priceRange.value.min) / (priceRange.value.max - priceRange.value.min)
  return chartHeight - padding - ratio * usableHeight
}

function resolveYWant(value: number) {
  const usableHeight = chartHeight - padding * 2
  const ratio = (value - wantCountRange.value.min) / (wantCountRange.value.max - wantCountRange.value.min)
  return chartHeight - padding - ratio * usableHeight
}

function buildPath(values: Array<number | null>, resolveY: (v: number) => number) {
  const commands = values
    .map((value, index) => {
      if (value === null || value === undefined) return null
      const prefix = index === 0 ? 'M' : 'L'
      return `${prefix} ${resolveX(index)} ${resolveY(value)}`
    })
    .filter(Boolean)
  return commands.join(' ')
}

// 格式化时间标签：04-05 14:30
function formatTimeLabel(snapshotTime: string) {
  if (!snapshotTime) return ''
  // snapshot_time 格式：2026-04-05T14:30:00
  const date = snapshotTime.slice(5, 10) // 04-05
  const time = snapshotTime.slice(11, 16) // 14:30
  return `${date} ${time}`
}

const avgPath = computed(() => buildPath(validPoints.value.map((point) => point.avg_price), resolveYPrice))
const wantCountPath = computed(() =>
  hasWantCountData.value ? buildPath(validPoints.value.map((point) => point.avg_want_count), resolveYWant) : ''
)

const areaPath = computed(() => {
  if (!avgPath.value || validPoints.value.length === 0) return ''
  const firstX = resolveX(0)
  const lastX = resolveX(validPoints.value.length - 1)
  const baseline = chartHeight - padding
  return `${avgPath.value} L ${lastX} ${baseline} L ${firstX} ${baseline} Z`
})
</script>

<template>
  <div class="app-surface-subtle p-4">
    <div class="mb-3 flex flex-col gap-3 text-xs uppercase tracking-[0.22em] text-slate-500 sm:flex-row sm:items-center sm:justify-between">
      <span>Daily Curve</span>
      <div class="flex items-center gap-3">
        <span class="inline-flex items-center gap-1">
          <span class="h-2.5 w-2.5 rounded-full bg-sky-600" />
          {{ t('results.chart.avgPrice') }}
        </span>
        <span v-if="hasWantCountData" class="inline-flex items-center gap-1">
          <span class="h-2.5 w-2.5 rounded-full bg-orange-500" />
          {{ t('results.chart.wantCount') }}
        </span>
      </div>
    </div>

    <div v-if="validPoints.length === 0" class="rounded-2xl border border-dashed border-slate-200 bg-white/70 px-4 py-10 text-center text-sm text-slate-500">
      {{ t('results.chart.noTrend') }}
    </div>

    <div v-else>
      <svg :viewBox="`0 0 ${chartWidth} ${chartHeight}`" class="h-[220px] w-full" role="img" :aria-label="t('results.chart.noTrend')">
        <defs>
          <linearGradient id="avg-area-fill" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#0284c7" stop-opacity="0.24" />
            <stop offset="100%" stop-color="#0284c7" stop-opacity="0" />
          </linearGradient>
        </defs>

        <!-- 水平参考线 -->
        <g>
          <line
            v-for="index in 4"
            :key="index"
            :x1="padding"
            :x2="chartWidth - padding"
            :y1="padding + ((chartHeight - padding * 2) / 4) * (index - 1)"
            :y2="padding + ((chartHeight - padding * 2) / 4) * (index - 1)"
            stroke="#cbd5e1"
            stroke-dasharray="4 6"
          />
        </g>

        <!-- 价格区域填充 -->
        <path :d="areaPath" fill="url(#avg-area-fill)" />

        <!-- 价格线（蓝色） -->
        <path :d="avgPath" fill="none" stroke="#0284c7" stroke-width="4" stroke-linecap="round" />

        <!-- 想要数线（橙色） -->
        <path
          v-if="wantCountPath"
          :d="wantCountPath"
          fill="none"
          stroke="#f97316"
          stroke-width="3"
          stroke-linecap="round"
        />

        <!-- 数据点和时间标签 -->
        <g v-for="(point, index) in validPoints" :key="point.run_id">
          <!-- 价格点 -->
          <circle
            v-if="point.avg_price !== null"
            :cx="resolveX(index)"
            :cy="resolveYPrice(point.avg_price as number)"
            r="5"
            fill="#0284c7"
          />

          <!-- 想要数点 -->
          <circle
            v-if="point.avg_want_count !== null"
            :cx="resolveX(index)"
            :cy="resolveYWant(point.avg_want_count as number)"
            r="4"
            fill="#f97316"
          />

          <!-- 时间标签 -->
          <text
            :x="resolveX(index)"
            :y="chartHeight - 6"
            text-anchor="middle"
            fill="#64748b"
            font-size="10"
          >
            {{ formatTimeLabel(point.snapshot_time) }}
          </text>
        </g>
      </svg>
    </div>
  </div>
</template>