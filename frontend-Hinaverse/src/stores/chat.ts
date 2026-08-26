import { defineStore } from 'pinia'
import { ref } from 'vue'

export type MessageRole = 'user' | 'hina' | 'system'

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  time: string
}

const now = () => new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

const uid = () => Math.random().toString(36).slice(2, 10)

const initialMessages: ChatMessage[] = [
  {
    id: uid(),
    role: 'system',
    content: '✦ 欢迎进入日奈宇宙。这里没有陌生人，只有还没说出的话。',
    time: now(),
  },
  {
    id: uid(),
    role: 'hina',
    content: '我是日奈。夜空已经安静了，你可以开始说第一颗星了。',
    time: now(),
  },
]

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([...initialMessages])
  const sending = ref(false)

  function sendUserMessage(text: string) {
    const trimmed = text.trim()
    if (!trimmed) return
    messages.value.push({
      id: uid(),
      role: 'user',
      content: trimmed,
      time: now(),
    })
  }

  function appendHinaReply(text: string) {
    messages.value.push({
      id: uid(),
      role: 'hina',
      content: text,
      time: now(),
    })
  }

  function setSending(val: boolean) {
    sending.value = val
  }

  return { messages, sending, sendUserMessage, appendHinaReply, setSending }
})