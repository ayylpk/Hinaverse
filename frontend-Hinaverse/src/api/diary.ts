/**
 * 日记接口封装（星历模块 · 只读）。
 * 对齐后端 routers/dairy.py：GET /api/diary → 当前用户全部日记（created_at 倒序）。
 * 本期只读展示，不做写入口（用户主动写的日记走现有 POST /api/diary，前端暂不提供）。
 */
import { http } from '@/api/http'

/** 后端 DiaryOut（schemas.py 对齐） */
export interface Diary {
  id: number
  user_id: number
  content: string
  created_at: string
}

/** 拉取当前用户全部日记（已按 created_at 倒序） */
export function fetchDiaries(): Promise<Diary[]> {
  return http.get<Diary[]>('/api/diary')
}
