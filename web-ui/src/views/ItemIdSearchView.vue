<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useToast } from '@/components/ui/toast/use-toast'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Search, ExternalLink, Clock, TrendingDown, TrendingUp } from 'lucide-vue-next'
import { searchByItemId, getSearchHistory, getPriceHistory, getWantCountHistory } from '@/api/sellers'
import type { ItemSearchResult, SearchHistoryItem, PriceHistoryPoint, WantCountHistoryPoint } from '@/types/seller.d.ts'
import PriceHistoryChart from '@/components/sellers/PriceHistoryChart.vue'
import WantCountChart from '@/components/sellers/WantCountChart.vue'

const { toast } = useToast()

const itemId = ref('')
const searchResult = ref<ItemSearchResult | null>(null)
const searchHistory = ref<SearchHistoryItem[]>([])
const priceHistory = ref<PriceHistoryPoint[]>([])
const wantCountHistory = ref<WantCountHistoryPoint[]>([])
const loading = ref(false)

async function handleSearch() {
  if (!itemId.value || !itemId.value.trim()) {
    toast({
      title: '提示',
      description: '请输入商品 ID',
      variant: 'default',
    })
    return
  }
  console.log('开始搜索，itemId:', itemId.value)
  loading.value = true
  try {
    console.log('调用 searchByItemId API')
    const result = await searchByItemId(itemId.value)
    console.log('搜索结果:', result)
    searchResult.value = result
    toast({
      title: '搜索成功',
      description: '已找到商品',
    })
    // 刷新历史
    searchHistory.value = await getSearchHistory(10)
    // 加载指标历史
    await loadMetricsHistory(itemId.value)
  } catch (error: any) {
    console.error('搜索失败:', error)
    toast({
      title: '搜索失败',
      description: error.message,
      variant: 'destructive',
    })
    searchResult.value = null
    priceHistory.value = []
    wantCountHistory.value = []
  } finally {
    console.log('搜索完成，重置 loading')
    loading.value = false
  }
}

async function loadMetricsHistory(id: string) {
  try {
    const [priceRes, wantRes] = await Promise.all([
      getPriceHistory(id, 30).catch(() => []),
      getWantCountHistory(id, 30).catch(() => []),
    ])
    priceHistory.value = priceRes
    wantCountHistory.value = wantRes
  } catch (error) {
    console.error('加载指标历史失败:', error)
  }
}

async function loadSearchHistory() {
  try {
    searchHistory.value = await getSearchHistory(10)
  } catch (error: any) {
    console.error('加载搜索历史失败:', error)
  }
}

function getPriceTrend() {
  if (priceHistory.value.length < 2) return null
  const first = priceHistory.value[0].price
  const last = priceHistory.value[priceHistory.value.length - 1].price
  if (last < first) return { direction: 'down', change: ((first - last) / first * 100).toFixed(1) }
  if (last > first) return { direction: 'up', change: ((last - first) / first * 100).toFixed(1) }
  return { direction: 'flat', change: '0' }
}

function getWantCountTrend() {
  if (wantCountHistory.value.length < 2) return null
  const first = wantCountHistory.value[0].want_count
  const last = wantCountHistory.value[wantCountHistory.value.length - 1].want_count
  if (last < first) return { direction: 'down', change: ((first - last) / first * 100).toFixed(1) }
  if (last > first) return { direction: 'up', change: ((last - first) / first * 100).toFixed(1) }
  return { direction: 'flat', change: '0' }
}

onMounted(() => {
  loadSearchHistory()
})
</script>

<template>
  <div class="space-y-6">
    <div>
      <h2 class="text-2xl font-bold">商品 ID 精确搜索</h2>
      <p class="text-sm text-slate-500">
        通过闲鱼商品 ID 快速查找特定商品，查看价格历史
      </p>
    </div>

    <Card>
      <CardHeader>
        <CardTitle>搜索商品</CardTitle>
        <CardDescription>
          输入商品 ID 进行搜索
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div class="flex gap-2">
          <div class="flex-1">
            <Input
              v-model="itemId"
              placeholder="请输入商品 ID"
              @keyup.enter="handleSearch"
            />
          </div>
          <Button @click="handleSearch" :disabled="loading">
            <Search class="w-4 h-4 mr-2" />
            搜索
          </Button>
        </div>

        <div v-if="searchHistory.length > 0" class="mt-4 space-y-2">
          <div class="flex items-center gap-2 text-sm text-slate-500">
            <Clock class="w-4 h-4" />
            最近搜索
          </div>
          <div class="flex flex-wrap gap-2">
            <Button
              v-for="(item, index) in searchHistory"
              :key="index"
              variant="outline"
              size="sm"
              @click="itemId = item.search_value"
            >
              {{ item.search_value }}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>

    <div v-if="searchResult" class="space-y-6">
      <!-- 商品详情卡片 -->
      <Card>
        <CardHeader>
          <CardTitle>商品信息</CardTitle>
        </CardHeader>
        <CardContent class="space-y-4">
          <div class="flex items-start gap-4">
            <img
              v-if="searchResult['商品图片列表']?.[0]"
              :src="searchResult['商品图片列表'][0]"
              class="h-32 w-32 rounded-lg object-cover"
            />
            <div class="flex-1">
              <h3 class="font-semibold text-lg line-clamp-2">{{ searchResult['商品标题'] }}</h3>
              <div class="flex items-center gap-3 mt-2">
                <p class="text-2xl font-bold text-rose-600">
                  ¥{{ searchResult['当前售价'] }}
                </p>
                <Badge v-if="searchResult['想要人数']" variant="secondary">
                  {{ searchResult['想要人数'] }} 人想要
                </Badge>
              </div>
            </div>
          </div>

          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t">
            <div>
              <p class="text-sm text-slate-500">浏览量</p>
              <p class="font-semibold">{{ searchResult['浏览量'] || '-' }}</p>
            </div>
            <div>
              <p class="text-sm text-slate-500">卖家</p>
              <p class="font-semibold">{{ searchResult['卖家昵称'] || '-' }}</p>
            </div>
            <div>
              <p class="text-sm text-slate-500">芝麻信用</p>
              <p class="font-semibold">{{ searchResult['芝麻信用'] || '-' }}</p>
            </div>
            <div>
              <p class="text-sm text-slate-500">卖家 ID</p>
              <p class="font-semibold text-sm">{{ searchResult['卖家 ID'] || '-' }}</p>
            </div>
          </div>

          <a
            :href="searchResult['商品链接']"
            target="_blank"
            class="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          >
            在闲鱼查看 <ExternalLink class="w-3 h-3" />
          </a>
        </CardContent>
      </Card>

      <!-- 指标历史图表 -->
      <Tabs default-value="price">
        <TabsList>
          <TabsTrigger value="price">
            <TrendingDown class="w-4 h-4 mr-2" />
            价格历史
          </TabsTrigger>
          <TabsTrigger value="want">
            <TrendingUp class="w-4 h-4 mr-2" />
            想要数历史
          </TabsTrigger>
        </TabsList>

        <TabsContent value="price">
          <Card>
            <CardHeader>
              <div class="flex items-center justify-between">
                <CardTitle>价格走势</CardTitle>
                <div v-if="getPriceTrend()" class="flex items-center gap-2">
                  <Badge :variant="getPriceTrend()?.direction === 'down' ? 'default' : 'secondary'"
                         :class="getPriceTrend()?.direction === 'down' ? 'bg-emerald-600' : 'bg-rose-600'">
                    <component :is="getPriceTrend()?.direction === 'down' ? TrendingDown : TrendingUp"
                               class="w-3 h-3 mr-1" />
                    {{ getPriceTrend()?.direction === 'down' ? '下降' : '上涨' }} {{ getPriceTrend()?.change }}%
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <PriceHistoryChart v-if="priceHistory.length > 0" :points="priceHistory" />
              <div v-else class="text-center py-8 text-slate-500">
                暂无价格历史数据
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="want">
          <Card>
            <CardHeader>
              <div class="flex items-center justify-between">
                <CardTitle>想要数走势</CardTitle>
                <div v-if="getWantCountTrend()" class="flex items-center gap-2">
                  <Badge :variant="getWantCountTrend()?.direction === 'up' ? 'default' : 'secondary'"
                         :class="getWantCountTrend()?.direction === 'up' ? 'bg-emerald-600' : 'bg-rose-600'">
                    <component :is="getWantCountTrend()?.direction === 'up' ? TrendingUp : TrendingDown"
                               class="w-3 h-3 mr-1" />
                    {{ getWantCountTrend()?.direction === 'up' ? '增加' : '减少' }} {{ getWantCountTrend()?.change }}%
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <WantCountChart v-if="wantCountHistory.length > 0" :points="wantCountHistory" />
              <div v-else class="text-center py-8 text-slate-500">
                暂无想要数历史数据
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  </div>
</template>
