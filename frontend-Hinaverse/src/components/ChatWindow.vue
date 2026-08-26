<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import hinaAvatar from '@/assets/img/hina-avatar.png'

const chat = useChatStore()
const input = ref('')
const listRef = ref<HTMLElement | null>(null)

/** 头像图片加载失败时兜底：换成 CSS 小月亮 */
const imgOk = ref(true)

// 一组更像人说话的 mock 回复
const mockReplies = [
  '嗯，我在听。慢慢说，不着急。',
  '听起来你今天不太好受。要不要先深呼吸一下？',
  '我懂这种感觉。不用急着证明什么，你已经很努力了。',
  '你愿意说出来，就已经很好了。我都在。',
  '嗯……换作是我，可能也会这样想。',
  '你不需要把一切都处理得很好。累了就歇一歇，我陪着你。',
  '夜越深，星星越亮。你现在说的话，正在变成你自己的星座。',
  '谢谢你愿意告诉我这些。我会把它收进夜空里，好好记住。',
]

function scrollToBottom() {
  nextTick(() => {
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight
    }
  })
}

watch(
  () => chat.messages.length,
  () => scrollToBottom()
)

async function onSend() {
  const text = input.value
  if (!text.trim() || chat.sending) return
  chat.sendUserMessage(text)
  input.value = ''
  chat.setSending(true)

  // 模拟日奈 "正在输入" 的延迟
  await new Promise((r) => setTimeout(r, 700 + Math.random() * 600))
  const reply = mockReplies[Math.floor(Math.random() * mockReplies.length)]
  chat.appendHinaReply(reply)
  chat.setSending(false)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    onSend()
  }
}
</script>

<template>
  <div class="chat-window">
    <!-- 顶部：月亮会呼吸 -->
    <header class="chat-header">
      <div class="hina-avatar">
        <div class="halo"></div>
        <div class="orbit">
          <span class="orbit-star"></span>
        </div>
        <img
          v-if="imgOk"
          :src="hinaAvatar"
          alt="日奈"
          class="avatar-img"
          @error="imgOk = false"
        />
        <div v-else class="css-doll">
          <div class="css-eye l"></div>
          <div class="css-eye r"></div>
        </div>
      </div>
      <div class="header-text">
        <div class="name">日奈 <span class="name-en">Hina</span></div>
        <div class="status">
          <span class="online-dot"></span>
          <span>正在陪伴你</span>
        </div>
      </div>
    </header>

    <!-- 星野消息区：你说的话，都会变成星星 -->
    <div ref="listRef" class="message-list starfield">
      <div
        v-for="msg in chat.messages"
        :key="msg.id"
        class="message-row"
        :class="msg.role"
      >
        <template v-if="msg.role === 'hina'">
          <div class="mini-avatar">
            <img v-if="imgOk" :src="hinaAvatar" alt="" class="mini-img" />
            <span v-else class="mini-dot"></span>
          </div>
        </template>
        <div class="bubble-wrap">
          <div class="bubble" :class="msg.role">
            {{ msg.content }}
          </div>
          <span class="time">{{ msg.time }}</span>
        </div>
      </div>

      <!-- 正在输入：三颗等待的星 -->
      <div v-if="chat.sending" class="message-row hina">
        <div class="mini-avatar">
          <span class="mini-dot"></span>
        </div>
        <div class="bubble-wrap">
          <div class="bubble hina typing">
            <span class="twinkle star"></span>
            <span class="twinkle star" style="animation-delay: 0.25s"></span>
            <span class="twinkle star" style="animation-delay: 0.5s"></span>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <footer class="chat-footer">
      <div class="input-bar">
        <textarea
          v-model="input"
          class="msg-input"
          placeholder="说点什么吧……"
          rows="1"
          @keydown="onKeydown"
        ></textarea>
        <el-button
          type="primary"
          class="send-btn"
          :loading="chat.sending"
          :disabled="!input.trim()"
          @click="onSend"
        >
          发射 <span class="arrow">✦</span>
        </el-button>
      </div>
      <div class="foot-row">
        <p class="hint">Enter 发送 · Shift + Enter 换行</p>
        <p class="cosmic">每句话，都是夜空里的一颗星 ✦</p>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.chat-window {
  width: 100%;
  max-width: 900px;
  height: calc(100vh - 116px);
  min-height: 560px;
  background: var(--nv-surface);
  backdrop-filter: blur(20px) saturate(140%);
  -webkit-backdrop-filter: blur(20px) saturate(140%);
  border-radius: var(--radius-xl);
  border: 1px solid var(--nv-border);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  /* 顶部一点月光洒在玻璃上 */
  background-image: radial-gradient(
      480px 140px at 50% 0%,
      rgba(242, 176, 76, 0.09),
      transparent 70%
    ),
    var(--nv-surface);
}

/* ---------- 顶部 ---------- */
.chat-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 28px;
  border-bottom: 1px solid var(--nv-border);
}

/* 签名元素：月亮头像，呼吸光晕 + 绕行小星 */
.hina-avatar {
  position: relative;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  flex-shrink: 0;
}
.halo {
  position: absolute;
  inset: -14px;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    rgba(242, 176, 76, 0.35) 0%,
    rgba(242, 176, 76, 0.1) 50%,
    transparent 72%
  );
  filter: blur(4px);
  animation: breathe 4s ease-in-out infinite;
}
.orbit {
  position: absolute;
  inset: -4px;
  border: 1px dashed rgba(185, 165, 224, 0.5);
  border-radius: 50%;
  animation: orbit 28s linear infinite;
  pointer-events: none;
}
.orbit-star {
  position: absolute;
  top: 3px;
  left: 50%;
  width: 5px;
  height: 5px;
  margin-left: -2.5px;
  border-radius: 50%;
  background: var(--nv-amber);
  box-shadow: 0 0 8px var(--nv-amber);
}
.avatar-img,
.css-doll {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid var(--nv-border-strong);
  z-index: 2;
}
/* 头像兜底：CSS 小月亮 */
.css-doll {
  background: linear-gradient(180deg, #f4c07a 0%, #dd9648 80%);
}
.css-eye {
  position: absolute;
  top: 26px;
  width: 5px;
  height: 7px;
  background: #2b1e12;
  border-radius: 50%;
}
.css-eye.l {
  left: 15px;
}
.css-eye.r {
  right: 15px;
}

.header-text .name {
  font-size: 17px;
  font-weight: 600;
  color: var(--nv-text);
  font-family: var(--font-display);
  letter-spacing: 1px;
}
.name-en {
  font-size: 11px;
  color: var(--nv-text-muted);
  font-family: var(--font-body);
  letter-spacing: 2px;
  margin-left: 6px;
}

.status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--nv-text-soft);
  margin-top: 2px;
}
.online-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--nv-amber);
  box-shadow: 0 0 8px var(--nv-amber);
  animation: breathe 2.6s ease-in-out infinite;
}

/* ---------- 消息列表（星野） ---------- */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 26px 28px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  position: relative; /* 星野层的定位锚点 */
}
/* 星野底纹比页面更淡，避免抢话 */
.message-list::before,
.message-list::after {
  opacity: 0.55;
  z-index: 0;
}

.message-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  max-width: 100%;
  position: relative;
  z-index: 1;
  animation: msg-in 0.3s ease-out both;
}
@keyframes msg-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-row.user {
  flex-direction: row-reverse;
}
.message-row.system {
  justify-content: center;
}

.mini-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  flex-shrink: 0;
  overflow: hidden;
  border: 1px solid var(--nv-border-strong);
  background: linear-gradient(180deg, #f4c07a, #dd9648);
}
.mini-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.mini-dot {
  display: block;
  width: 100%;
  height: 100%;
}

.bubble-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 72%;
}
.message-row.user .bubble-wrap {
  align-items: flex-end;
}

.bubble {
  padding: 11px 16px;
  border-radius: var(--radius-md);
  font-size: 15px;
  line-height: 1.65;
  word-break: break-word;
  white-space: pre-wrap;
}

/* 日奈：月光里的玻璃气泡 */
.bubble.hina {
  background: var(--nv-bubble-hina);
  border: 1px solid var(--nv-border);
  border-bottom-left-radius: 6px;
  color: var(--nv-text);
  backdrop-filter: blur(6px);
}

/* 用户：像一颗亮起的星 */
.bubble.user {
  background: linear-gradient(135deg, var(--nv-bubble-user-start), var(--nv-bubble-user-end));
  color: var(--nv-amber-ink);
  border-bottom-right-radius: 6px;
  box-shadow: 0 2px 14px rgba(242, 176, 76, 0.22);
  font-weight: 500;
}

.bubble.system {
  background: transparent;
  color: var(--nv-text-muted);
  font-size: 13px;
  text-align: center;
  padding: 4px 0;
  letter-spacing: 0.5px;
}

.time {
  font-size: 11px;
  color: var(--nv-text-muted);
  padding: 0 4px;
}

/* 正在输入：三颗等待的星 */
.bubble.typing {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 15px 17px;
}
.star {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--nv-amber);
  box-shadow: 0 0 6px var(--nv-amber);
}

/* ---------- 输入区 ---------- */
.chat-footer {
  padding: 14px 26px 12px;
  border-top: 1px solid var(--nv-border);
}

.input-bar {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}

.msg-input {
  flex: 1;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  font-size: 15px;
  line-height: 1.5;
  resize: none;
  outline: none;
  font-family: inherit;
  color: var(--nv-text);
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
  max-height: 120px;
  overflow-y: auto;
}
.msg-input::placeholder {
  color: var(--nv-text-muted);
}
.msg-input:focus {
  border-color: var(--nv-amber);
  background: rgba(255, 255, 255, 0.07);
  box-shadow: 0 0 0 3px rgba(242, 176, 76, 0.12);
}

.send-btn {
  height: 46px;
  padding: 0 26px;
  border-radius: var(--radius-md);
  font-size: 15px;
  letter-spacing: 2px;
}
.send-btn .arrow {
  margin-left: 2px;
}

.foot-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 8px 2px 0;
}
.hint {
  font-size: 12px;
  color: var(--nv-text-muted);
  margin: 0;
}
.cosmic {
  font-size: 12px;
  color: var(--nv-text-muted);
  margin: 0;
  letter-spacing: 0.5px;
}
.cosmic .twinkle {
  color: var(--nv-amber);
}

/* ---------- 响应式 ---------- */
@media (max-width: 720px) {
  .chat-window {
    height: calc(100vh - 100px);
    border-radius: var(--radius-lg);
  }
  .bubble-wrap {
    max-width: 84%;
  }
  .foot-row .cosmic {
    display: none;
  }
}
</style>