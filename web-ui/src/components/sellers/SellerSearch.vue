<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useToast } from '@/components/ui/toast/use-toast'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Search, User, Star, CreditCard } from 'lucide-vue-next'
import { getSellerInfo } from '@/api/sellers'

const { toast } = useToast()

const sellerId = ref('')
const sellerInfo = ref<any>(null)
const loading = ref(false)

async function handleSearch() {
  if (!sellerId.value) return
  loading.value = true
  try {
    const info = await getSellerInfo(sellerId.value)
    sellerInfo.value = info
    toast({
      title: '搜索成功',
      description: '已找到卖家信息',
    })
  } catch (error: any) {
    toast({
      title: '搜索失败',
      description: error.message,
      variant: 'destructive',
    })
    sellerInfo.value = null
  } finally {
    loading.value = false
  }
}

function formatDate(dateStr: string | null) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

onMounted(() => {
  // 可选：从 URL 参数加载 sellerId
})
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle>卖家 ID 搜索</CardTitle>
      <CardDescription>
        通过卖家 ID 查询卖家信息和信用
      </CardDescription>
    </CardHeader>
    <CardContent class="space-y-4">
      <div class="flex gap-2">
        <div class="flex-1">
          <Input
            v-model="sellerId"
            placeholder="请输入卖家 ID"
            @keyup.enter="handleSearch"
          />
        </div>
        <Button @click="handleSearch" :disabled="loading || !sellerId">
          <Search class="w-4 h-4 mr-2" />
          搜索
        </Button>
      </div>

      <div v-if="sellerInfo" class="rounded-lg border bg-slate-50 p-4 space-y-3">
        <div class="flex items-center gap-3">
          <div class="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
            <User class="w-6 h-6 text-primary" />
          </div>
          <div class="flex-1">
            <h4 class="font-semibold text-lg">{{ sellerInfo['卖家昵称'] || '-' }}</h4>
            <p class="text-sm text-slate-500">ID: {{ sellerInfo['卖家 ID'] }}</p>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div class="rounded-lg bg-white p-3 border">
            <div class="flex items-center gap-2 text-sm text-slate-500">
              <Star class="w-4 h-4" />
              芝麻信用
            </div>
            <p class="text-lg font-bold text-amber-600 mt-1">
              {{ sellerInfo['芝麻信用'] || '未认证' }}
            </p>
          </div>
          <div class="rounded-lg bg-white p-3 border">
            <div class="flex items-center gap-2 text-sm text-slate-500">
              <CreditCard class="w-4 h-4" />
              卖家类型
            </div>
            <p class="text-lg font-bold mt-1">
              {{ sellerInfo['卖家类型'] || '个人' }}
            </p>
          </div>
        </div>

        <div class="text-xs text-slate-500">
          <p>最后更新时间：{{ formatDate(sellerInfo.last_updated) }}</p>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
