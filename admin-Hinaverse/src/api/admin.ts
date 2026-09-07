/**
 * 运营台统计 API（/api/admin，仅管理员）。
 * 与后端 routers/admin.py + schemas.py（Admin* 段）严格对齐。
 */
import { http } from '@/api/http'
import type { CrisisEvent, CrisisMessage } from '@/api/crisis'

/** 指标卡六项（时间口径：活跃/消息=近 7 天滚动；今日新增=当日 0 点起；在线=WS 实时） */
export interface AdminStatsCards {
  total_users: number
  new_users_today: number
  active_users_7d: number
  messages_7d: number
  open_crises: number
  online_users: number
}

/** 7 日趋势单日（后端已缺日补零，末位是今天） */
export interface AdminTrendPoint {
  date: string // YYYY-MM-DD
  new_users: number
  messages: number
  crises: number
}

/** 危机分布一格（全历史，风险等级 × 状态） */
export interface AdminCrisisDist {
  risk_level: string
  status: string
  count: number
}

export interface AdminStats {
  cards: AdminStatsCards
  trend: AdminTrendPoint[]
  crisis_dist: AdminCrisisDist[]
}

/** 用户表行（msg_count/last_active 口径=role user，发言才算活跃） */
export interface AdminUser {
  id: number
  username: string
  nickname: string
  role: string
  created_at: string
  last_active: string | null
  msg_count: number
  crisis_count: number
}

export interface AdminUserPage {
  total: number
  page: number
  size: number
  items: AdminUser[]
}

/** 用户详情（本地 SQL 部分，秒开）；画像走 fetchUserPortrait 懒加载 */
export interface AdminUserDetail {
  user: AdminUser
  messages: CrisisMessage[]
  crises: CrisisEvent[]
}

export interface AdminPortrait {
  user_id: number
  portrait: string | null
}

/** 大盘：指标卡 + 趋势 + 危机分布，一屏一个请求 */
export function fetchAdminStats(): Promise<AdminStats> {
  return http.get<AdminStats>('/api/admin/stats')
}

/** 用户表：q 模糊搜用户名/昵称，page 从 1 起 */
export function fetchAdminUsers(params: { q?: string; page?: number; size?: number } = {}): Promise<AdminUserPage> {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.page) qs.set('page', String(params.page))
  if (params.size) qs.set('size', String(params.size))
  const query = qs.toString()
  return http.get<AdminUserPage>(`/api/admin/users${query ? `?${query}` : ''}`)
}

/** 用户详情：资料 + 跨会话最近 20 条 + 危机史 */
export function fetchUserDetail(userId: number): Promise<AdminUserDetail> {
  return http.get<AdminUserDetail>(`/api/admin/users/${userId}/detail`)
}

/** 画像转发（服务端 TTL 5min）：无画像/记忆服务不可达都回 portrait=null，前端画空态 */
export function fetchUserPortrait(userId: number): Promise<AdminPortrait> {
  return http.get<AdminPortrait>(`/api/admin/users/${userId}/portrait`)
}
