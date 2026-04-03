<script setup lang="ts">
import { ref } from 'vue'
import { useToast } from '@/components/ui/toast/use-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { searchByItemId, getSearchHistory } from '@/api/sellers'
import type { ItemSearchResult, SearchHistoryItem } from '@/types/seller.d.ts'
import { Search, ExternalLink, Clock } from 'lucide-vue-next'

const { toast } = useToast()

const itemId = ref('')
const searchResult = ref<ItemSearchResult | null>(null)
const searchHistory = ref<SearchHistoryItem[]>([])
const loading = ref(false)

async function handleSearch() {
  if (!itemId.value) return
  loading.value = true
  try {
    const result = await searchByItemId(itemId.value)
    searchResult.value = result
    toast({
      title: '搜索成功',
      description: '已找到商品',
    })
    // 刷新历史
    searchHistory.value = await getSearchHistory(10)
  } catch (error: any) {
    toast({
      title: '搜索失败',
      description: error.message,
      variant: 'destructive',
    })
  } finally {
    loading.value = false
  }
}

async function loadSearchHistory() {
  try {
    searchHistory.value = await getSearchHistory(10)
  } catch (error: any) {
    console.error('加载搜索历史失败:', error)
  }
}

// 初始化加载历史
loadSearchHistory()
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle>商品 ID 精确搜索</CardTitle>
      <CardDescription>
        通过闲鱼商品 ID 快速查找特定商品
      </CardDescription>
    </CardHeader>
    <CardContent class="space-y-4">
      <div class="grid gap-2">
        <Label for="item-id">商品 ID</Label>
        <div class="flex gap-2">
          <Input
            id="item-id"
            v-model="itemId"
            placeholder="请输入商品 ID"
            @keyup.enter="handleSearch"
          />
          <Button @click="handleSearch" :disabled="loading || !itemId">
            <Search class="w-4 h-4 mr-2" />
            搜索
          </Button>
        </div>
      </div>

      <div v-if="searchResult" class="rounded-lg border bg-slate-50 p-4">
        <div class="flex items-start gap-3 mb-3">
          <img
            v-if="searchResult.商品图片列表?.[0]"
            :src="searchResult.商品图片列表[0]"
            class="h-20 w-20 rounded-lg object-cover"
          />
          <div class="flex-1">
            <h4 class="font-semibold line-clamp-2">{{ searchResult.商品标题 }}</h4>
            <p class="text-lg font-bold text-rose-600 mt-1">
              ¥{{ searchResult.当前售价 }}
            </p>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-2 text-sm">
          <div>
            <span class="text-slate-500">想要:</span>
            <span class="ml-2 font-medium">{{ searchResult.想要人数 || '-' }}</span>
          </div>
          <div>
            <span class="text-slate-500">浏览:</span>
            <span class="ml-2 font-medium">{{ searchResult.浏览量 || '-' }}</span>
          </div>
          <div>
            <span class="text-slate-500">卖家:</span>
            <span class="ml-2 font-medium">{{ searchResult.卖家昵称 || '-' }}</span>
          </div>
          <div>
            <span class="text-slate-500">信用:</span>
            <span class="ml-2 font-medium">{{ searchResult.芝麻信用 || '-' }}</span>
          </div>
        </div>

        <a
          :href="searchResult.商品链接"
          target="_blank"
          class="mt-3 inline-flex items-center gap-1 text-sm text-primary hover:underline"
        >
          查看详情 <ExternalLink class="w-3 h-3" />
        </a>
      </div>

      <div v-if="searchHistory.length > 0" class="space-y-2">
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
</template>
