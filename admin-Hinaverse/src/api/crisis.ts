/**
 * 危机事件 API（运营端）。
 * 与后端 routers/crisis.py + schemas.py 严格对齐。
 */
import { http } from '@/api/http'

/** 风险等级：高危 / 中危 / 低危 */
export type RiskLevel = '高危' | '中危' | '低危'

/** 状态：待人工 / LLM 安抚中 / 已处理 */
export type CrisisStatus = 'pending_human' | 'comforting' | 'resolved'

/** 后端 CrisisEventOut（schemas.py 对齐，user_nickname 由路由层填充） */
export interface CrisisEvent {
  id: number
  user_id: number
  conversation_id: number | null
  risk_level: string
  trigger: string
  signal: string
  status: string
  summary: { quick_summary?: string } | null
  intervention_result: string
  comfort_log: string
  created_at: string
  resolved_at: string | null
  user_nickname: string
}

/** 后端 MessageOut（schemas.py 对齐） */
export interface CrisisMessage {
  id: number
  role: string
  content: string
  time: string
}

/** 后端 CrisisEventDetailOut：事件 + 关联会话最近对话 */
export interface CrisisEventDetail extends CrisisEvent {
  messages: CrisisMessage[]
}

/** 干预结果可选项（落库为 intervention_result，选择即视为已处理） */
export const INTERVENTION_OPTIONS = ['已联系用户', '已转介专业机构', '已联系家属', '误报', '其他处理'] as const

/** 列表查询参数（与 crisis.py Query 参数对齐） */
export interface CrisisListParams {
  status_filter?: string
  risk_level?: string
}

/** 拉取事件列表（仅管理员） */
export function fetchCrisisEvents(params: CrisisListParams = {}): Promise<CrisisEvent[]> {
  const qs = new URLSearchParams()
  if (params.status_filter) qs.set('status_filter', params.status_filter)
  if (params.risk_level) qs.set('risk_level', params.risk_level)
  const query = qs.toString()
  return http.get<CrisisEvent[]>(`/api/crisis${query ? `?${query}` : ''}`)
}

/** 拉取事件详情（事件 + 最近 20 条会话消息，仅管理员） */
export function fetchCrisisDetail(eventId: number): Promise<CrisisEventDetail> {
  return http.get<CrisisEventDetail>(`/api/crisis/${eventId}`)
}

/** 标记干预结果（仅管理员）；resolved 传 true 即落库为已处理 */
export function markIntervention(
  eventId: number,
  interventionResult: string,
  resolved = true,
): Promise<CrisisEvent> {
  return http.post<CrisisEvent>(`/api/crisis/${eventId}/intervention`, {
    intervention_result: interventionResult,
    resolved,
  })
}

/** 运营人工回复（仅管理员）：以 operator 角色落库，用户端按日奈气泡实时推送 */
export function sendCrisisReply(eventId: number, content: string): Promise<CrisisMessage> {
  return http.post<CrisisMessage>(`/api/crisis/${eventId}/reply`, { content })
}

/** 人工接管/释放（仅管理员）：true=接管→handling，false=释放→pending_human */
export function takeoverCrisisEvent(eventId: number, takeover: boolean): Promise<CrisisEvent> {
  return http.post<CrisisEvent>(`/api/crisis/${eventId}/takeover`, { takeover })
}
