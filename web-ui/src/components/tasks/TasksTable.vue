<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Task } from '@/types/task.d.ts'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import {
  Play,
  Square,
  Pencil,
  Trash2,
  User,
  Keyboard,
  Hash,
  Clock,
  Layers,
  MapPin,
  RefreshCcw,
  Search,
  Pause,
  PlayCircle
} from 'lucide-vue-next'
import { formatCountdown, formatNextRunAbsolute } from '@/lib/taskSchedule'

interface Props {
  tasks: Task[]
  isLoading: boolean
  stoppingIds?: Set<number>
}

const props = defineProps<Props>()
const { t } = useI18n()
const isStopping = (id: number) => props.stoppingIds?.has(id) ?? false
const isItemIdTask = (task: Task) => task.task_type === 'item_id'
const nowMs = ref(Date.now())
let timer: number | null = null

onMounted(() => {
  timer = window.setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (timer !== null) {
    window.clearInterval(timer)
  }
})

const resolveAccountStrategyLabel = (task: Task) => {
  if (task.account_strategy === 'rotate') return t('tasks.table.accountRotate')
  if (task.account_strategy === 'fixed') return t('tasks.table.accountFixed')
  return t('tasks.table.accountAuto')
}

const resolveAccountName = (task: Task) => {
  if (!task.account_state_file) return t('tasks.table.systemSelected')
  const segments = task.account_state_file.split('/')
  const filename = segments[segments.length - 1] || task.account_state_file
  return filename.replace('.json', '')
}

const resolveCountdownText = (task: Task) => {
  if (!task.cron) return t('tasks.table.manualTrigger')
  if (!task.enabled) return t('tasks.table.disabled')
  if (task.is_queued && !task.is_running) return t('tasks.table.queuedForRun')
  return formatCountdown(task.next_run_at, nowMs.value) || t('tasks.table.waitingSchedule')
}

const resolveCountdownTone = (task: Task) => {
  if (!task.cron) return 'text-slate-400'
  if (!task.enabled) return 'text-slate-400'
  return 'text-amber-600'
}

const resolveNextRunLabel = (task: Task) => {
  if (!task.cron || !task.enabled || !task.next_run_at) return null
  return formatNextRunAbsolute(task.next_run_at)
}

const isQueued = (task: Task) => task.is_queued && !task.is_running

const resolveStatusLabel = (task: Task) => {
  if (task.is_running) return t('tasks.table.active')
  if (isQueued(task)) return t('tasks.table.queued')
  return t('tasks.table.idle')
}

const resolveStatusDotClass = (task: Task) => {
  if (task.is_running) return 'bg-emerald-500 animate-pulse'
  if (isQueued(task)) return 'bg-amber-500 animate-pulse'
  return 'bg-slate-300'
}

const resolveStatusTextClass = (task: Task) => {
  if (task.is_running) return 'text-emerald-600'
  if (isQueued(task)) return 'text-amber-600'
  return 'text-slate-400'
}

const emit = defineEmits<{
  (e: 'delete-task', taskId: number): void
  (e: 'run-task', taskId: number): void
  (e: 'stop-task', taskId: number): void
  (e: 'pause-task', taskId: number): void
  (e: 'resume-task', taskId: number): void
  (e: 'edit-task', task: Task): void
  (e: 'toggle-enabled', task: Task, enabled: boolean): void
}>()
</script>

<template>
  <div class="border-none shadow-glass rounded-2xl bg-white/60 backdrop-blur-md overflow-hidden animate-fade-in">
    <Table>
      <TableHeader class="bg-slate-50/50 border-b border-slate-100">
        <TableRow>
          <TableHead class="w-[80px] px-6 text-slate-500 font-bold uppercase text-[10px] tracking-wider text-center">{{ t('tasks.table.headers.status') }}</TableHead>
          <TableHead class="min-w-[300px] text-slate-500 font-bold uppercase text-[10px] tracking-wider text-left">{{ t('tasks.table.headers.details') }}</TableHead>
          <TableHead class="w-[180px] text-slate-500 font-bold uppercase text-[10px] tracking-wider text-left">{{ t('tasks.table.headers.crawl') }}</TableHead>
          <TableHead class="w-[180px] text-slate-500 font-bold uppercase text-[10px] tracking-wider text-center">{{ t('tasks.table.headers.mode') }}</TableHead>
          <TableHead class="w-[140px] text-slate-500 font-bold uppercase text-[10px] tracking-wider text-center">{{ t('tasks.table.headers.schedule') }}</TableHead>
          <TableHead class="w-[160px] px-6 text-slate-500 font-bold uppercase text-[10px] tracking-wider text-right">{{ t('tasks.table.headers.actions') }}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <template v-if="isLoading && tasks.length === 0">
          <TableRow>
            <TableCell :colspan="6" class="h-32 text-center">
              <div class="flex flex-col items-center justify-center gap-2 text-slate-400">
                <RefreshCcw class="w-6 h-6 animate-spin" />
                <span class="text-sm font-medium italic">{{ t('tasks.table.syncing') }}</span>
              </div>
            </TableCell>
          </TableRow>
        </template>
        <template v-else-if="tasks.length === 0">
          <TableRow>
            <TableCell :colspan="6" class="h-40 text-center">
               <div class="flex flex-col items-center justify-center gap-2 text-slate-300">
                  <Layers class="w-12 h-12 opacity-20" />
                  <p class="text-sm font-bold">{{ t('tasks.table.empty') }}</p>
               </div>
            </TableCell>
          </TableRow>
        </template>
        <template v-else>
          <TableRow
            v-for="task in tasks"
            :key="task.id"
            class="group hover:bg-white/80 transition-all duration-300 border-b border-slate-100/50 last:border-0"
          >
            <!-- Column 1: Status -->
            <TableCell class="px-6 align-middle">
              <div class="flex flex-col items-center gap-2.5">
                <Switch
                  :model-value="task.enabled"
                  class="data-[state=checked]:bg-primary scale-90"
                  @update:model-value="(val: boolean) => emit('toggle-enabled', task, val)"
                />
                <div class="flex items-center gap-1.5">
                  <div :class="[ 'w-1.5 h-1.5 rounded-full shadow-sm', resolveStatusDotClass(task) ]"></div>
                  <span :class="[ 'text-[9px] font-black tracking-widest uppercase', resolveStatusTextClass(task) ]">
                    {{ resolveStatusLabel(task) }}
                  </span>
                </div>
              </div>
            </TableCell>

            <!-- Column 2: Task Info -->
            <TableCell class="align-middle">
              <div class="flex flex-col gap-1.5 py-1">
                <div class="flex items-center gap-2">
                  <span class="text-base font-black text-slate-800 tracking-tight group-hover:text-primary transition-colors">{{ task.task_name }}</span>
                  <Badge 
                    variant="outline" 
                    :class="[
                      'h-4 px-1.5 text-[9px] font-black border-none tracking-tighter', 
                      isItemIdTask(task) ? 'bg-violet-50 text-violet-600' : 'bg-blue-50 text-blue-500'
                    ]"
                  >
                    <component :is="isItemIdTask(task) ? Hash : Keyboard" class="w-2.5 h-2.5 mr-1" />
                    {{ isItemIdTask(task) ? 'ID DIRECT' : 'KEYWORD' }}
                  </Badge>
                </div>
                
                <div class="flex items-center gap-2">
                   <div class="flex items-center gap-1.5 bg-slate-100/80 text-slate-600 px-2 py-0.5 rounded-md text-[11px] font-bold border border-slate-200/50">
                      <Search class="w-3 h-3 text-slate-400" />
                      {{ isItemIdTask(task) ? `${task.item_id_list?.length || 0} 个商品 ID` : task.keyword }}
                   </div>
                </div>

                <div class="flex items-center gap-2 mt-0.5">
                   <div class="flex items-center gap-1 text-[10px] font-bold text-slate-400 uppercase tracking-tight">
                      <User class="w-3 h-3" /> {{ resolveAccountStrategyLabel(task) }}
                   </div>
                   <div class="h-1 w-1 rounded-full bg-slate-200"></div>
                   <div class="text-[10px] font-medium text-slate-400 truncate max-w-[120px]">
                      {{ resolveAccountName(task) }}
                   </div>
                </div>
              </div>
            </TableCell>

            <!-- Column 3: Crawl Config -->
            <TableCell class="align-middle text-left">
              <div class="space-y-2">
                <div class="flex items-baseline gap-0.5">
                  <span class="text-[10px] font-bold text-slate-400 mr-1 italic">¥</span>
                  <span class="text-sm font-black text-slate-700 tracking-tighter">
                    {{ task.min_price || 0 }} <span class="text-slate-300 font-normal mx-0.5">-</span> {{ task.max_price || 'MAX' }}
                  </span>
                </div>
                <div class="flex flex-wrap gap-1.5">
                  <Badge variant="outline" class="text-[9px] h-4 border-slate-100 text-slate-400 px-1.5 font-bold bg-white/40">
                    {{ task.personal_only ? t('tasks.table.personalOnly') : t('common.all') }}
                  </Badge>
                  <Badge variant="outline" class="text-[9px] h-4 border-slate-100 text-slate-400 px-1.5 font-bold bg-white/40">
                    {{ task.free_shipping ? t('tasks.table.freeShipping') : t('common.all') }}
                  </Badge>
                  <div v-if="task.region" class="flex items-center gap-0.5 text-[9px] font-bold text-slate-400 px-1.5 h-4 bg-slate-50/50 rounded border border-slate-100 truncate max-w-[80px]">
                    <MapPin class="w-2.5 h-2.5" /> {{ task.region }}
                  </div>
                </div>
              </div>
            </TableCell>

            <!-- Column 4: Matching Details -->
            <TableCell class="align-middle text-center">
              <div class="inline-flex flex-col items-center gap-2">
                <div v-if="!isItemIdTask(task)" class="bg-blue-50/30 p-2 rounded-xl border border-blue-100/50">
                  <div class="text-xs font-black text-blue-600">{{ t('tasks.table.keywordStrategies', { count: task.keyword_rules?.length || 0 }) }}</div>
                  <div class="text-[9px] font-bold text-blue-400/70 uppercase mt-0.5 tracking-tighter">OR Logic</div>
                </div>
                <div v-else class="rounded-xl border border-violet-100/70 bg-violet-50/40 p-2">
                  <div class="text-xs font-black text-violet-600">{{ task.item_id_list?.length || 0 }} 个指定商品</div>
                  <div class="mt-0.5 text-[9px] font-bold uppercase tracking-tighter text-violet-400/80">Direct Monitor</div>
                </div>
              </div>
            </TableCell>

            <!-- Column 5: Cron & Pages -->
            <TableCell class="align-middle text-center">
              <div class="inline-flex flex-col items-center gap-1.5">
                <div class="flex items-center gap-1.5 bg-slate-100/50 border border-slate-200/30 px-2 py-1 rounded-lg">
                  <Clock class="w-3 h-3 text-slate-400" />
                  <span class="text-[11px] font-black text-slate-600 tracking-tight">{{ task.cron || 'MANUAL' }}</span>
                </div>
                <div
                  class="px-2 py-1 rounded-md bg-amber-50/60 border border-amber-100/80 min-w-[112px]"
                  :class="!task.cron || !task.enabled ? 'bg-slate-50 border-slate-100' : ''"
                  :title="resolveNextRunLabel(task) || undefined"
                >
                  <div
                    class="text-[10px] font-black tracking-tight"
                    :class="resolveCountdownTone(task)"
                  >
                    {{ resolveCountdownText(task) }}
                  </div>
                  <div
                    v-if="resolveNextRunLabel(task)"
                    class="text-[9px] font-medium text-slate-400 mt-0.5"
                  >
                    {{ resolveNextRunLabel(task) }}
                  </div>
                </div>
                <div class="flex items-center gap-1 text-[9px] font-black text-slate-400 uppercase tracking-widest">
                  <Layers class="w-3 h-3 opacity-50" /> {{ task.max_pages || 3 }}P
                </div>
              </div>
            </TableCell>

            <!-- Column 6: Actions -->
            <TableCell class="px-6 align-middle text-right">
              <div class="flex justify-end items-center gap-2">
                <Button
                  v-if="isQueued(task)"
                  size="sm"
                  variant="outline"
                  class="h-8 px-3 rounded-lg border-amber-200 bg-amber-50/70 text-amber-700 pointer-events-none"
                  disabled
                >
                  <RefreshCcw class="w-3 h-3 mr-1.5 animate-spin" />
                  <span class="font-bold text-[11px]">{{ t('tasks.table.queued') }}</span>
                </Button>
                <Button
                  v-else-if="!task.is_running"
                  size="sm"
                  variant="default"
                  class="h-8 px-3 rounded-lg shadow-sm transition-all active:scale-95 text-white border-none"
                  :class="task.enabled ? 'bg-primary hover:bg-primary/90' : 'bg-slate-200 text-slate-400 pointer-events-none opacity-50'"
                  @click="emit('run-task', task.id)"
                >
                  <Play class="w-3 h-3 mr-1.5 fill-current" />
                  <span class="font-bold text-[11px]">{{ t('tasks.table.start') }}</span>
                </Button>
                <Button
                  v-else
                  size="sm"
                  variant="destructive"
                  class="h-8 px-3 rounded-lg shadow-sm active:scale-95 border-none"
                  :disabled="isStopping(task.id)"
                  @click="emit('stop-task', task.id)"
                >
                  <Square v-if="!isStopping(task.id)" class="w-3 h-3 mr-1.5 fill-current" />
                  <RefreshCcw v-else class="w-3 h-3 mr-1.5 animate-spin" />
                  <span class="font-bold text-[11px]">{{ isStopping(task.id) ? t('tasks.table.stopping') : t('tasks.table.stop') }}</span>
                </Button>

                <!-- Pause/Resume button -->
                <template v-if="task.cron && task.enabled">
                  <Button
                    v-if="task.is_paused"
                    size="sm"
                    variant="outline"
                    class="h-8 px-2 rounded-lg border-amber-200 text-amber-600 hover:bg-amber-50 hover:text-amber-700"
                    @click="emit('resume-task', task.id)"
                  >
                    <PlayCircle class="w-3.5 h-3.5" />
                  </Button>
                  <Button
                    v-else
                    size="sm"
                    variant="outline"
                    class="h-8 px-2 rounded-lg border-slate-200 text-slate-500 hover:bg-slate-50"
                    @click="emit('pause-task', task.id)"
                  >
                    <Pause class="w-3.5 h-3.5" />
                  </Button>
                </template>

                <div class="flex items-center gap-0.5 ml-1">
                  <Button
                    size="icon"
                    variant="ghost"
                    class="w-8 h-8 rounded-full text-slate-400 hover:text-primary hover:bg-primary/5 transition-colors"
                    @click="emit('edit-task', task)"
                  >
                    <Pencil class="w-3.5 h-3.5" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    class="w-8 h-8 rounded-full text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-colors"
                    @click="emit('delete-task', task.id)"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>
            </TableCell>
          </TableRow>
        </template>
      </TableBody>
    </Table>
  </div>
</template>

<style scoped>
:deep(td) {
  @apply py-3 px-4;
}
:deep(th) {
  @apply h-11 px-4;
}
</style>
