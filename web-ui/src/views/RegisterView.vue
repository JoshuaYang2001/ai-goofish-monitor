<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { registerAccount } from '@/api/auth'
import LocaleToggle from '@/components/layout/LocaleToggle.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

const { t } = useI18n()
const adminUsername = ref('')
const adminPassword = ref('')
const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const isLoading = ref(false)
const error = ref('')
const success = ref('')

async function handleRegister() {
  error.value = ''
  success.value = ''
  if (
    !adminUsername.value
    || !adminPassword.value
    || !username.value
    || !password.value
    || !confirmPassword.value
  ) {
    error.value = t('register.errors.missingFields')
    return
  }
  if (password.value !== confirmPassword.value) {
    error.value = t('register.errors.passwordMismatch')
    return
  }

  isLoading.value = true
  try {
    const response = await registerAccount({
      admin_username: adminUsername.value,
      admin_password: adminPassword.value,
      username: username.value,
      password: password.value,
    })
    success.value = t('register.success', { username: response.user.username })
    adminPassword.value = ''
    username.value = ''
    password.value = ''
    confirmPassword.value = ''
  } catch (reason) {
    error.value = reason instanceof Error
      ? reason.message
      : t('register.errors.unexpected')
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-100 px-4 py-10">
    <div aria-hidden="true" class="absolute inset-0">
      <div class="absolute left-[-10%] top-[-10%] h-72 w-72 rounded-full bg-primary/10 blur-3xl"></div>
      <div class="absolute bottom-[-10%] right-[-5%] h-72 w-72 rounded-full bg-blue-300/10 blur-3xl"></div>
    </div>
    <div class="absolute right-6 top-6">
      <LocaleToggle />
    </div>
    <Card class="app-surface relative z-10 w-full max-w-lg border-none">
      <CardHeader>
        <CardTitle class="text-center text-2xl">{{ t('register.title') }}</CardTitle>
        <CardDescription class="text-center">{{ t('register.description') }}</CardDescription>
      </CardHeader>
      <form @submit.prevent="handleRegister">
        <CardContent class="grid gap-5">
          <section class="grid gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
            <div>
              <h2 class="text-sm font-bold text-slate-800">{{ t('register.adminSection') }}</h2>
              <p class="mt-1 text-xs text-slate-500">{{ t('register.adminHint') }}</p>
            </div>
            <div class="grid gap-2 sm:grid-cols-2">
              <div class="grid gap-2">
                <Label for="admin-username">{{ t('register.adminUsername') }}</Label>
                <Input
                  id="admin-username"
                  v-model="adminUsername"
                  type="text"
                  autocomplete="username"
                  required
                />
              </div>
              <div class="grid gap-2">
                <Label for="admin-password">{{ t('register.adminPassword') }}</Label>
                <Input
                  id="admin-password"
                  v-model="adminPassword"
                  type="password"
                  autocomplete="current-password"
                  required
                />
              </div>
            </div>
          </section>

          <section class="grid gap-3">
            <h2 class="text-sm font-bold text-slate-800">{{ t('register.accountSection') }}</h2>
            <div class="grid gap-2">
              <Label for="new-username">{{ t('register.username') }}</Label>
              <Input id="new-username" v-model="username" type="text" autocomplete="off" required />
            </div>
            <div class="grid gap-3 sm:grid-cols-2">
              <div class="grid gap-2">
                <Label for="new-password">{{ t('register.password') }}</Label>
                <Input
                  id="new-password"
                  v-model="password"
                  type="password"
                  autocomplete="new-password"
                  minlength="8"
                  required
                />
              </div>
              <div class="grid gap-2">
                <Label for="confirm-password">{{ t('register.confirmPassword') }}</Label>
                <Input
                  id="confirm-password"
                  v-model="confirmPassword"
                  type="password"
                  autocomplete="new-password"
                  minlength="8"
                  required
                />
              </div>
            </div>
            <p class="text-xs text-slate-500">{{ t('register.passwordHint') }}</p>
          </section>

          <div v-if="error" class="rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-600" role="alert">
            {{ error }}
          </div>
          <div v-if="success" class="rounded-lg bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700" role="status">
            {{ success }}
          </div>
        </CardContent>
        <CardFooter class="flex-col gap-2">
          <Button class="w-full" type="submit" :disabled="isLoading">
            {{ isLoading ? t('register.submitting') : t('register.submit') }}
          </Button>
          <Button variant="link" as-child>
            <RouterLink :to="{ name: 'Login' }">{{ t('register.backToLogin') }}</RouterLink>
          </Button>
        </CardFooter>
      </form>
    </Card>
  </div>
</template>
