/**
 * 打卡接口封装（星历模块）。
 * 对齐后端 routers/checkin.py：
 *   POST   /api/checkin         新建（content 1..500，date 可选缺省当天）
 *   GET    /api/checkin         全部打卡（date 倒序；?date=YYYY-MM-DD 过滤）
 *   PATCH  /api/checkin/{id}    打卡/取消打卡（status: done|todo）
 *   DELETE /api/checkin/{id}    删除（204）
 */
import { http } from '@/api/http'

/** 后端 CheckinOut（schemas.py 对齐） */
export interface Checkin {
  id: number
  user_id: number
  content: string
  /** 打卡归属日（YYYY-MM-DD，纯日期） */
  date: string
  /** todo（未完成）/ done（已完成） */
  status: 'todo' | 'done'
  created_at: string
}

/** 新建打卡：date 缺省当天（后端处理），传了按传的算 */
export function createCheckin(content: string, date?: string): Promise<Checkin> {
  return http.post<Checkin>('/api/checkin', date ? { content, date } : { content })
}

/** 全部打卡；可选只取某天 */
export function fetchCheckins(date?: string): Promise<Checkin[]> {
  return http.get<Checkin[]>(`/api/checkin${date ? `?date=${encodeURIComponent(date)}` : ''}`)
}

/** 打卡/取消打卡标记 */
export function updateCheckinStatus(id: number, status: 'todo' | 'done'): Promise<Checkin> {
  return http.patch<Checkin>(`/api/checkin/${id}`, { status })
}

/** 删除一条打卡（后端返回 204，无响应体） */
export function deleteCheckin(id: number): Promise<void> {
  return http.delete<void>(`/api/checkin/${id}`)
}
