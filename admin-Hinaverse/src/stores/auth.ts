/**
 * 认证 store（运营台）：登录 / 首管理员注册 / 当前用户 / 退出。
 * 与后端 auth.py 对齐：
 *   POST /api/auth/login → 200 { token, user }   （账号密码错 → 401）
 *   POST /api/auth/register → 201 { token, user }（is_admin=true 走部署码链）
 *   GET  /api/auth/admin-register-status → { open }（首管理员注册通道）
 *   GET  /api/auth/me    → 200 UserOut            （带 Bearer token，含 role）
 *
 * token 存 localStorage('hina_token' / 'hina_user')，与用户端同 key。
 * 运营台登录后必须校验 role === "admin"，非管理员一律登出。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { http, type AuthUser } from '@/api/http'

const TOKEN_KEY = 'hina_token'
const USER_KEY = 'hina_user'

/** 从 localStorage 恢复已保存的用户；格式坏了就返回 null */
function loadSavedUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref<AuthUser | null>(loadSavedUser())

  const isLoggedIn = computed(() => !!token.value)

  /** 是否管理员（运营台唯一放行角色） */
  const isAdmin = computed(() => user.value?.role === 'admin')

  /** 登录成功后的统一落库：token + user 双写 localStorage */
  function applyAuth(data: { token: string; user: AuthUser }) {
    token.value = data.token
    user.value = data.user
    localStorage.setItem(TOKEN_KEY, data.token)
    localStorage.setItem(USER_KEY, JSON.stringify(data.user))
  }

  /** 登录：失败抛 ApiError（401 detail 是「账号或密码不正确」） */
  async function login(username: string, password: string): Promise<void> {
    const data = await http.post<{ token: string; user: AuthUser }>('/api/auth/login', {
      username,
      password,
    })
    applyAuth(data)
  }

  /** 首管理员注册（is_admin=true 走部署码链，失败抛 ApiError 展示后端 detail） */
  async function registerAdmin(username: string, password: string, initCode: string): Promise<void> {
    const data = await http.post<{ token: string; user: AuthUser }>('/api/auth/register', {
      username,
      password,
      is_admin: true,
      init_code: initCode,
    })
    applyAuth(data)
  }

  /** 首管理员注册通道状态（无 admin 且已配置部署码时开放） */
  async function fetchAdminRegStatus(): Promise<{ open: boolean }> {
    return http.get<{ open: boolean }>('/api/auth/admin-register-status')
  }

  /** 刷新页面后从后端拉最新资料（含 role，角色可能被运维改过） */
  async function fetchMe(): Promise<void> {
    if (!isLoggedIn.value) return
    user.value = await http.get<AuthUser>('/api/auth/me')
    localStorage.setItem(USER_KEY, JSON.stringify(user.value))
  }

  /** 退出：后端 JWT 无状态，前端清掉本地凭证即可 */
  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  return { token, user, isLoggedIn, isAdmin, login, registerAdmin, fetchAdminRegStatus, fetchMe, logout }
})
