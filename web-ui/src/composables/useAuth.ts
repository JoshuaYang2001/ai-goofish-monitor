import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { wsService } from '@/services/websocket'

// Global State
interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
  tenant: { id: string; name: string }
  user: { id: number; username: string; role: string }
}

const username = ref<string | null>(localStorage.getItem('auth_username'))
const tenantId = ref<string | null>(localStorage.getItem('auth_tenant_id'))
const tenantName = ref<string | null>(localStorage.getItem('auth_tenant_name'))
const isLoggedIn = ref(Boolean(localStorage.getItem('auth_access_token')))
let refreshPromise: Promise<boolean> | null = null

function storeSession(session: AuthResponse) {
  username.value = session.user.username
  tenantId.value = session.tenant.id
  tenantName.value = session.tenant.name
  isLoggedIn.value = true
  localStorage.setItem('auth_username', session.user.username)
  localStorage.setItem('auth_tenant_id', session.tenant.id)
  localStorage.setItem('auth_tenant_name', session.tenant.name)
  localStorage.setItem('auth_access_token', session.access_token)
  localStorage.setItem('auth_refresh_token', session.refresh_token)
}

export function getAccessToken(): string | null {
  return localStorage.getItem('auth_access_token')
}

export async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise
  refreshPromise = (async () => {
    const refreshToken = localStorage.getItem('auth_refresh_token')
    if (!refreshToken) return false
    const response = await fetch('/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!response.ok) return false
    storeSession(await response.json() as AuthResponse)
    return true
  })().catch(() => false).finally(() => {
    refreshPromise = null
  })
  return refreshPromise
}

export function useAuth() {
  const router = useRouter()

  const isAuthenticated = computed(() => isLoggedIn.value)

  async function logout() {
    const refreshToken = localStorage.getItem('auth_refresh_token')
    if (refreshToken) {
      void fetch('/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
    }
    username.value = null
    tenantId.value = null
    tenantName.value = null
    isLoggedIn.value = false
    localStorage.removeItem('auth_username')
    localStorage.removeItem('auth_tenant_id')
    localStorage.removeItem('auth_tenant_name')
    localStorage.removeItem('auth_access_token')
    localStorage.removeItem('auth_refresh_token')

    // 停止 WebSocket 连接
    wsService.stop()

    // Redirect to login if using router
    if (router) {
      router.push('/login')
    } else {
      window.location.href = '/login'
    }
  }

  async function login(user: string, pass: string): Promise<boolean> {
    try {
      const response = await fetch('/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username: user, password: pass }),
      })

      if (response.ok) {
        storeSession(await response.json() as AuthResponse)
        wsService.start()
        return true
      } else {
        return false
      }
    } catch (e) {
      console.error('Login error', e)
      return false
    }
  }

  return {
    username,
    tenantId,
    tenantName,
    isAuthenticated,
    login,
    logout
  }
}
