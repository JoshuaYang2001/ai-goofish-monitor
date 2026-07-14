<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useSettings } from '@/composables/useSettings'
import type { NotificationSettingsUpdate, NotificationTestResponse } from '@/api/settings'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { toast } from '@/components/ui/toast'
import NotificationSettingsPanel from '@/components/settings/NotificationSettingsPanel.vue'
import RotationSettingsPanel from '@/components/settings/RotationSettingsPanel.vue'
const { t } = useI18n()

const {
  notificationSettings,
  rotationSettings,
  systemStatus,
  isLoading,
  isSaving,
  isReady,
  error,
  refreshStatus,
  saveNotificationSettings,
  testNotification,
  saveRotationSettings,
} = useSettings()

const activeTab = ref('notifications')
const route = useRoute()
const validTabs = new Set(['notifications', 'rotation', 'status'])

function notifySuccess(title: string, description?: string) {
  toast({ title, description })
}

function notifyError(title: string, description?: string) {
  toast({ title, description, variant: 'destructive' })
}

async function handleSaveNotifications(payload: NotificationSettingsUpdate) {
  try {
    await saveNotificationSettings(payload)
    notifySuccess(t('settings.notifications.saved'))
  } catch (e) {
    notifyError(t('settings.notifications.saveFailed'), (e as Error).message)
  }
}

async function handleTestNotification(payload: {
  channel?: string
  settings: NotificationSettingsUpdate
}): Promise<NotificationTestResponse> {
  try {
    const result = await testNotification(payload)
    return result
  } catch (e) {
    notifyError(t('settings.notifications.testFailed'), (e as Error).message)
    throw e
  }
}

async function handleSaveRotation() {
  try {
    await saveRotationSettings()
    notifySuccess(t('settings.rotation.saved'))
  } catch (e) {
    notifyError(t('settings.rotation.saveFailed'), (e as Error).message)
  }
}

watch(
  () => route.query.tab,
  (tab) => {
    if (typeof tab === 'string' && validTabs.has(tab)) {
      activeTab.value = tab
    }
  },
  { immediate: true }
)

</script>

<template>
  <div>
    <h1 class="text-2xl font-bold text-gray-800 mb-6">{{ t('settings.title') }}</h1>
    
    <div v-if="error" class="app-alert-error mb-4" role="alert">
      {{ error.message }}
    </div>

    <Tabs v-model="activeTab" class="w-full">
      <TabsList class="mb-4 flex w-full flex-nowrap justify-start gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1">
        <TabsTrigger class="shrink-0" value="rotation">{{ t('settings.tabs.rotation') }}</TabsTrigger>
        <TabsTrigger class="shrink-0" value="notifications">{{ t('settings.tabs.notifications') }}</TabsTrigger>
        <TabsTrigger class="shrink-0" value="status">{{ t('settings.tabs.status') }}</TabsTrigger>
      </TabsList>

      <!-- Rotation Tab -->
      <TabsContent value="rotation">
        <RotationSettingsPanel
          :settings="rotationSettings"
          :is-ready="isReady"
          :is-saving="isSaving"
          @save="handleSaveRotation"
        />
      </TabsContent>

      <!-- Notifications Tab -->
      <TabsContent value="notifications">
        <NotificationSettingsPanel
          :settings="notificationSettings"
          :is-ready="isReady"
          :is-saving="isSaving"
          :save-settings="handleSaveNotifications"
          :test-settings="handleTestNotification"
        />
      </TabsContent>

      <!-- Status Tab -->
      <TabsContent value="status">
        <Card>
          <CardHeader>
            <CardTitle>{{ t('settings.status.title') }}</CardTitle>
            <div class="flex justify-end">
                <Button variant="outline" size="sm" @click="refreshStatus" :disabled="isLoading">{{ t('settings.status.refresh') }}</Button>
            </div>
          </CardHeader>
          <CardContent>
            <div v-if="systemStatus" class="space-y-6">
              <!-- Scraper Process Status -->
              <div class="flex items-center justify-between border-b pb-4">
                <div>
                  <h3 class="font-medium">{{ t('settings.status.scraper') }}</h3>
                  <p class="text-sm text-gray-500">{{ t('settings.status.scraperDescription') }}</p>
                </div>
                <span :class="systemStatus.scraper_running ? 'text-green-600 font-bold bg-green-50 px-3 py-1 rounded-full' : 'text-gray-500 bg-gray-100 px-3 py-1 rounded-full'">
                  {{ systemStatus.scraper_running ? t('common.running') : t('common.idle') }}
                </span>
              </div>

              <!-- Env Config Status -->
              <div>
                <div class="flex items-center justify-between mb-4">
                    <div>
                        <h3 class="font-medium">{{ t('settings.status.env') }}</h3>
                        <p class="text-sm text-gray-500">{{ t('settings.status.envDescription') }}</p>
                    </div>
                    <span :class="systemStatus.env_file.exists ? 'text-green-600 font-bold bg-green-50 px-3 py-1 rounded-full' : 'text-red-600 font-bold bg-red-50 px-3 py-1 rounded-full'">
                        {{ systemStatus.env_file.exists ? t('settings.status.loaded') : t('settings.status.missing') }}
                    </span>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div class="p-3 border rounded-lg" :class="systemStatus.configured_notification_channels?.length ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200'">
                         <div class="flex justify-between items-center">
                            <span class="font-medium text-sm">{{ t('settings.status.channels') }}</span>
                             <span class="text-xs font-bold" :class="systemStatus.configured_notification_channels?.length ? 'text-green-700' : 'text-gray-500'">
                                {{ systemStatus.configured_notification_channels?.length ? t('common.active') : t('common.inactive') }}
                            </span>
                        </div>
                         <div class="text-xs text-gray-500 mt-1">
                            {{ systemStatus.configured_notification_channels?.join(', ') || t('settings.status.none') }}
                        </div>
                    </div>
                </div>
              </div>
            </div>
            <div v-else class="text-center py-8 text-gray-500">
                {{ t('settings.status.fetching') }}
            </div>
          </CardContent>
        </Card>
      </TabsContent>

    </Tabs>
  </div>
</template>
