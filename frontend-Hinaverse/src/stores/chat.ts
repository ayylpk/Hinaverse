/**
 * 聊天 store：会话准备（HTTP）+ 消息收发（WebSocket）。
 *
 * 前后端协议（见 backend app/ws/protocol.py）：
 *   发： {type:"message", conversation_id, content}
 *   收： {type:"typing"} → {type:"message", conversation_id, msg:{id, role, content, time}}
 *   收： {type:"system", content}（拦截/系统提示）
 *   收： {type:"active", conversation_id, msg}（服务端主动消息，结构同 message）
 *   心跳：服务端 30s 发 ping，ws.ts 自动回 pong，这里不用管
 *
 * 身份：userId 不参与消息体（服务端从 JWT 解），auth.user.id 只用于 UI 归属展示。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { http } from '@/api/http'
import { wsClient, type WsStatus } from '@/api/ws'
import { useAuthStore } from '@/stores/auth'

export type MessageRole = 'user' | 'hina' | 'system'
export interface ChatMessage {
  /** 后端消息 id 是 number；本地乐观渲染的临时消息用 string，避免和落库 id 混 */
  id: string | number
  role: MessageRole
  content: string
  time: string
}

/** 后端 ConversationOut 的字段子集 */
export interface ConversationInfo {
  id: number
  title: string
  created_at: string
  last_message: string
  unread_count: number
}

const nowTime = () =>
  new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
const tempId = () => `tmp-${Date.now()}-${Math.floor(Math.random() * 1e6)}`

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  /** 日奈「正在输入」：typing 事件或本地发出消息时置 true，收到回复置 false */
  const sending = ref(false)
  const conversationId = ref<number | null>(null)
  const wsStatus = ref<WsStatus>('idle')

  // init 守卫：并发调用 ensureReady 也只跑一次（类似 Java 双重检查锁 + volatile）
  let _initPromise: Promise<void> | null = null
  let _wsBound = false

  /** 三件事不重复做：取/建会话 → 拉历史 → 连 WS。幂等 */
  async function ensureReady(): Promise<void> {
    if (_initPromise) return _initPromise
    _initPromise = _doInit()
      .catch((e: unknown) => {
        ElMessage.error(`进入夜空失败：${e instanceof Error ? e.message : String(e)}`)
      })
      .finally(() => {
        _initPromise = null
      })
    return _initPromise
  }

  async function _doInit(): Promise<void> {
    const auth = useAuthStore()
    if (!auth.isLoggedIn) return

    // 1. 会话：取最近一个，没有就新建（后端新建时会落一条日奈开场白）
    const convs = await http.get<ConversationInfo[]>('/api/conversations')
    const conv = convs[0] ?? (await http.post<ConversationInfo>('/api/conversations'))
    conversationId.value = conv.id

    // 2. 历史：后端已按时间正序返回（默认 50 条）
    const hist = await http.get<{ messages: ChatMessage[]; has_more: boolean }>(
      `/api/conversations/${conv.id}/messages?limit=50`,
    )
    messages.value = hist.messages

    // 3. 未读清零（后台执行，失败不阻塞）+ 建立长连接
    http.post(`/api/conversations/${conv.id}/read`).catch(() => {})
    _bindWsHandlers()
    wsClient.connect()
  }

  /** 注册 WS 处理器（只注册一次，防 ensureReady 重复进入时重复绑定） */
  function _bindWsHandlers(): void {
    if (_wsBound) return
    _wsBound = true

    // 入站分发表：对应后端 InboundHub 的「type → 处理函数」
    wsClient.on('typing', () => {
      sending.value = true
    })
    // 日奈回复 和 主动消息（日终总结等）结构一致，走同一个处理
    wsClient.on('message', (data) => _pushAgentMessage(data))
    wsClient.on('active', (data) => _pushAgentMessage(data))
    wsClient.on('system', (data) => {
      messages.value.push({
        id: tempId(),
        role: 'system',
        content: String(data.content ?? ''),
        time: nowTime(),
      })
    })

    // 连接状态：断线提示 + 重连成功后提示（只在真的经历了断线时提示一次）
    let last: WsStatus = 'idle'
    wsClient.onStatus((s) => {
      wsStatus.value = s
      if (s === 'reconnecting') {
        sending.value = false
        ElMessage.warning('夜风断了，正在重新接上…')
      } else if (s === 'open' && last === 'reconnecting') {
        ElMessage.success('已重新连上')
      }
      last = s
    })
  }

  /** 收到的 agent 消息（type=message / active）：校验会话归属后上屏 */
  function _pushAgentMessage(data: Record<string, unknown>): void {
    const convId = Number(data.conversation_id)
    if (convId && convId !== conversationId.value) return // 不是当前会话的消息，忽略
    const msg = data.msg as ChatMessage | undefined
    if (!msg || typeof msg.content !== 'string') return
    // role 用后端给的值（hina / system），不要硬编码 hina：
    // 人工接管的提示与运营回复都是 role=system，硬编码会把"已转人工"显示成日奈在说
    const role: MessageRole = msg.role === 'system' ? 'system' : 'hina'
    messages.value.push({ id: msg.id, role, content: msg.content, time: msg.time })
    sending.value = false
  }

  /** 发一条消息：乐观上屏 + WS 送出。没连着时提示用户，不让消息静默丢失 */
  async function sendMessage(text: string): Promise<void> {
    const content = text.trim()
    if (!content) return
    await ensureReady()
    if (conversationId.value === null) return

    // 后端不回显用户自己的消息，前端本地「乐观渲染」先上屏（星先亮起来）
    messages.value.push({ id: tempId(), role: 'user', content, time: nowTime() })
    sending.value = true

    const ok = wsClient.send('message', {
      conversation_id: conversationId.value,
      content,
    })
    if (!ok) {
      sending.value = false
      messages.value.push({
        id: tempId(),
        role: 'system',
        content: '连接还没接上，这条没送出去。正在重连，稍后再试…',
        time: nowTime(),
      })
    }
  }

  /** 登出时调用：断开连接 + 清空本地状态，下次登录重新初始化 */
  function reset(): void {
    wsClient.disconnect()
    messages.value = []
    sending.value = false
    conversationId.value = null
    wsStatus.value = 'idle'
  }

  return { messages, sending, conversationId, wsStatus, ensureReady, sendMessage, reset }
})