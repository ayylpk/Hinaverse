/**
 * 后端请求封装：原生 fetch 薄封装，零依赖（与用户端 http.ts 同款）。
 * 1. 自动带 token（Authorization: Bearer xxx）
 * 2. JSON 序列化/反序列化
 * 3. 错误统一转成 ApiError，业务层只管 try/catch
 * 4. 401 自动清本地凭证并跳登录页（token 过期/被吊销时兜底登出）
 */

/** 后端 UserOut 结构（schemas.py 对齐，含 role） */
export interface AuthUser {
  id: number
  username: string
  nickname: string
  avatar: string
  role: string
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
const USER_KEY = 'hina_user'

/** 从 localStorage 读 token（与用户端同 key，反正不同端口互不干扰） */
function authHeader(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** 401 兜底：清凭证回登录页（登录请求本身的 401 不触发，避免误跳） */
function handleUnauthorized() {
  if (localStorage.getItem(TOKEN_KEY)) {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    if (window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
  }
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

  if (res.status === 401) {
    handleUnauthorized()
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
