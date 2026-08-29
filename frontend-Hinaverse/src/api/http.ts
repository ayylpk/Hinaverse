/**
 * 后端请求封装：原生 fetch 薄封装，零依赖。
 *
 * 为什么不用 axios：项目只有登录/会话/WS 三类请求，WebSocket 本来就是原生的，
 * 只为 REST 装一个库不值。封装只做三件事：
 * 1. 自动带 token（Authorization: Bearer xxx）
 * 2. JSON 序列化/反序列化
 * 3. 错误统一转成 ApiError，业务层只管 try/catch
 *
 * token 谁管：auth store 负责「写」localStorage('hina_token')，
 * 这里负责「读」——http 不依赖 store，store 不依赖 http，没有循环 import。
 */

/** 后端 UserOut 结构（schemas.py 对齐） */
export interface AuthUser {
  id: number
  username: string
  nickname: string
  avatar: string
}

/** 登录/注册响应：{ token, user } */
export interface AuthResponse {
  token: string
  user: AuthUser
}

/** 统一错误：status 是 HTTP 状态码，detail 是后端返回的人话（或兜底文案） */
export class ApiError extends Error {
  status: number
  /** 后端 detail 原文（也可能是 422 数组里第一条 msg） */
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

const TOKEN_KEY = 'hina_token'

/** 从 localStorage 读 token（存储此前的 mock 也是这个 key，无缝替换） */
function authHeader(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** 解析 FastAPI 的错误体 {detail}：detail 可能是字符串，也可能是 422 的数组 */
function parseDetail(body: unknown): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    // 422 校验错误：detail 是 [{loc, msg, type}] 数组，取第一条的消息
    if (Array.isArray(detail) && detail.length > 0 && 'msg' in detail[0]) {
      return String(detail[0].msg)
    }
  }
  return '请求失败，请稍后再试'
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      headers: {
        'Content-Type': 'application/json',
        ...authHeader(),
        ...(options.headers || {}),
      },
      ...options,
    })
  } catch {
    // fetch 只有网络层面失败才会走到这里（后端没起来、断网等）
    throw new ApiError(0, '无法连接服务器，请确认后端已启动')
  }

  if (!res.ok) {
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      /* 非 JSON 错误体，用默认文案 */
    }
    throw new ApiError(res.status, parseDetail(body))
  }

  // 204 无内容等空响应
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const http = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) }),
}