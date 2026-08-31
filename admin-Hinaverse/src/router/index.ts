import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { TOKEN_KEY, USER_KEY } from '@/api/http'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
  },
  {
    path: '/',
    name: 'Crisis',
    component: () => import('@/views/CrisisView.vue'),
  },
  {
    path: '/takeover',
    name: 'Takeover',
    component: () => import('@/views/TakeoverView.vue'),
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  // '/admin/' 与 vite.config.ts 的 base 对应：路由跳转/刷新都带子路径前缀
  history: createWebHistory('/admin/'),
  routes,
})

/**
 * 路由守卫：
 * - 未登录（无 token）→ 登录页
 * - 已登录但角色不是 admin（本地存的是普通用户）→ 清凭证回登录页
 * - 登录页且已有 admin 凭证 → 直达列表
 */
router.beforeEach((to) => {
  const token = localStorage.getItem(TOKEN_KEY)
  const userRaw = localStorage.getItem(USER_KEY)
  let role = ''
  try {
    role = userRaw ? (JSON.parse(userRaw) as { role?: string }).role ?? '' : ''
  } catch {
    /* 本地缓存损坏按未登录处理 */
  }

  if (to.name !== 'Login' && !token) {
    return { name: 'Login' }
  }
  // 有 token 但非 admin：本地凭证不可用，清掉回登录页（真正的 403 由后端兜底）
  if (to.name !== 'Login' && token && role !== 'admin') {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    return { name: 'Login' }
  }
  if (to.name === 'Login' && token && role === 'admin') {
    return { name: 'Crisis' }
  }
})

export default router
