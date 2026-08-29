/**
 * WebSocket 客户端：一条长连接 + 前端版「分发表」。
 *
 * 角色对照后端（app/ws/Hub.py）：
 *   后端 InboundHub 按 type 分发客户端消息  → 这里 on(type, cb) 是它收到的消息的镜像
 *   后端 OutboundHub 是统一出口             → 这里所有收到的消息往下分发给注册方
 *
 * 自带三件事：
 *   1. 心跳：服务端 30s 发 {type:"ping"}，这里自动回 {type:"pong"}，连接才不被踢
 *   2. 断线重连：指数退避 1s→2s→4s…封顶 30s
 *   3. 鉴权失败（关闭码 4003）不重连——token 无效，重连没意义，等重新登录
 *
 * 注意：身份由 token 传入（/ws?token=…），消息体不需要带 userId，
 * 服务端从 JWT 解出当前用户——和 Java 里从 SecurityContext 取当前用户一个道理。
 */

export type WsStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'
type WsPayload = Record<string, unknown>
type WsHandler = (data: WsPayload) => void

class WsClient {
  private ws: WebSocket | null = null
  /** type → 处理函数集合（前端版分发表） */
  private handlers = new Map<string, Set<WsHandler>>()
  private statusListeners = new Set<(s: WsStatus) => void>()
  private retryCount = 0
  private manualClose = false

  /** 建立连接；已在连接/已连接时是 no-op（防重复开连接互相顶掉） */
  connect(): void {
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return
    }
    const token = localStorage.getItem('hina_token')
    if (!token) return

    this.manualClose = false
    this._setStatus(this.retryCount > 0 ? 'reconnecting' : 'connecting')

    const ws = new WebSocket(`/ws?token=${encodeURIComponent(token)}`)
    this.ws = ws
    ws.onopen = () => {
      this.retryCount = 0 // 连上后重置退避计数
      this._setStatus('open')
    }
    ws.onmessage = (e) => this._dispatch(e.data)
    ws.onclose = (e) => this._handleClose(e.code)
    ws.onerror = () => {
      /* 浏览器会随后触发 onclose，统一在那处理，这里什么都不做 */
    }
  }

  private _handleClose(code: number): void {
    this.ws = null
    if (this.manualClose) {
      this._setStatus('closed')
      return
    }
    if (code === 4003) {
      // 鉴权失败：token 无效/过期，重连只会再次被拒，停下来等用户重新登录
      this._setStatus('closed')
      return
    }
    // 非主动断开：指数退避重连
    const delay = Math.min(1000 * 2 ** this.retryCount, 30000)
    this.retryCount += 1
    this._setStatus('reconnecting')
    setTimeout(() => this.connect(), delay)
  }

  /** 收到一条服务端消息：解析 → 心跳特判 → 按 type 分发 */
  private _dispatch(raw: string): void {
    let data: WsPayload
    try {
      data = JSON.parse(raw) as WsPayload
    } catch {
      return // 非 JSON（如服务端调试输出），忽略
    }
    const type = String(data.type ?? '')

    // 心跳：服务端 ping → 回 pong，保持连接活跃
    if (type === 'ping') {
      this._sendRaw({ type: 'pong' })
      return
    }

    const cbs = this.handlers.get(type)
    if (!cbs) return // 未注册的类型忽略（跟后端 InboundHub 的行为一致）
    for (const cb of cbs) cb(data)
  }

  /** 发一条客户端消息；返回是否真的送出去了（没连着会 false，由 store 兜底提示） */
  send(type: string, payload: WsPayload): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false
    this._sendRaw({ type, ...payload })
    return true
  }

  private _sendRaw(obj: Record<string, unknown>): void {
    this.ws?.send(JSON.stringify(obj))
  }

  /** 注册消息处理：on('message', cb) 等，type 见后端协议 protocol.py */
  on(type: string, cb: WsHandler): void {
    const set = this.handlers.get(type)
    if (set) set.add(cb)
    else this.handlers.set(type, new Set([cb]))
  }

  /** 连接状态变化监听（UI 展示 / 断线提示用） */
  onStatus(cb: (s: WsStatus) => void): void {
    this.statusListeners.add(cb)
  }

  /** 主动断开（登出时调用），之后不再重连 */
  disconnect(): void {
    this.manualClose = true
    this.ws?.close()
    this.ws = null
    this.retryCount = 0
    this._setStatus('closed')
  }

  private _setStatus(s: WsStatus): void {
    for (const cb of this.statusListeners) cb(s)
  }
}

/**
 * 全局单例：整个页面只有一条长连接。
 * 注意别开第二条——后端 OutboundHub 的连接表是 user_id → 单个连接的覆盖关系，
 * 开两条会把第一条顶掉，消息就乱套了。
 */
export const wsClient = new WsClient()