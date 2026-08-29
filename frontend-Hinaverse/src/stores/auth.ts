/**
 * 认证 store：登录 / 注册 / 当前用户 / 退出。
 *
 * 与后端 auth.py 严格对齐：
 *   POST /api/auth/register → 201 { token, user }
 *   POST /api/auth/login    → 200 { token, user }   （账号密码错 → 401）
 *   GET  /api/auth/me       → 200 UserOut            （带 Bearer token）
 *   PUT  /api/auth/profile  → 200 UserOut
 *
 * token 的「读」在 api/http.ts（请求自动带头），这里只管「写」。
 * 存 localStorage 的 key 沿用原来的 'hina_token' / 'hina_user'，
 * 路由守卫和视觉代码一行不用改。
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

  /** 有 token 就算已登录（token 过期与否由请求时的 401 触达） */
  const isLoggedIn = computed(() => !!token.value)

  /** 兼容旧组件叫法：HomeView/ProfileDialog 直接读 profile.nickname / profile.avatar。
   *  未登录时为兜底空对象（这些组件只在登录后可达，正常不会读到默认值） */
  const profile = computed<AuthUser>(() =>
    user.value ?? { id: 0, username: '', nickname: '', avatar: '' },
  )

  /** 登录/注册成功后的统一落库：token + user 双写 localStorage */
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

  /** 注册：用户名被占用后端返回 400「用户名已被使用」，前端拿到直接展示 */
  async function register(username: string, password: string): Promise<void> {
    const data = await http.post<{ token: string; user: AuthUser }>('/api/auth/register', {
      username,
      password,
    })
    applyAuth(data)
  }

  /** 退出：后端 JWT 无状态，前端清掉本地凭证即可 */
  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  /** 刷新页面后从后端拉最新资料（昵称/头像可能被别处改过） */
  async function fetchMe(): Promise<void> {
    if (!isLoggedIn.value) return
    user.value = await http.get<AuthUser>('/api/auth/me')
    localStorage.setItem(USER_KEY, JSON.stringify(user.value))
  }

  /** 更新资料：字段与后端 ProfileUpdateRequest 对齐（snake_case）。
   *  改密码时传 current_password + new_password，后端负责校验；失败抛 ApiError */
  async function updateProfile(patch: ProfileUpdatePayload): Promise<void> {
    const updated = await http.put<AuthUser>('/api/auth/profile', patch)
    user.value = updated
    localStorage.setItem(USER_KEY, JSON.stringify(updated))
  }

  return { token, user, profile, isLoggedIn, login, register, logout, fetchMe, updateProfile }
})

/** updateProfile 的入参：昵称/头像/改密码均可选（见后端 ProfileUpdateRequest） */
export interface ProfileUpdatePayload {
  nickname?: string
  avatar?: string
  current_password?: string
  new_password?: string
}