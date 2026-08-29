<script setup lang="ts">
/**
 * 人工接管工作台（真通道，无 WebSocket 轮询）：
 * - 待接管队列：GET /api/crisis?status_filter=pending_human（handling 天然不进队列）
 * - 点击接管 → POST /api/crisis/{id}/takeover {takeover:true} 成功后写本地接管列表（快照，真状态以后端为准）
 * - 我的接管：可同时接管多个用户/事件；被他人接管的事件点进来会 409「已被接管」，自动刷新队列
 * - 对话：GET /api/crisis/{id} 快照 + 运营回复走 POST /api/crisis/{id}/reply（system 角色实时推用户端）
 * - 提交干预结果 → 复用 POST /api/crisis/{id}/intervention → resolved 后移出接管
 * - 实时性：30s 轮询队列（静默刷新）+ 页面切回前台立即刷新
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Headset, Refresh } from '@element-plus/icons-vue'
import AdminSidebar from '@/components/AdminSidebar.vue'
import { ApiError } from '@/api/http'
import {
  fetchCrisisEvents,
  fetchCrisisDetail,
  markIntervention,
  sendCrisisReply,
  takeoverCrisisEvent,
  INTERVENTION_OPTIONS,
  type CrisisEvent,
  type CrisisEventDetail,
} from '@/api/crisis'

const TAKEOVER_KEY = 'hina_takeover'
const POLL_INTERVAL = 30_000

/** 一条接管记录：事件快照 + 接管时间（真状态在后端，本地仅作列表展示） */
interface TakeoverRecord {
  event: CrisisEvent
  takenAt: string
}

// ── 待接管队列 ──
const queue = ref<CrisisEvent[]>([])
const queueLoading = ref(false)
const queueError = ref('')

// ── 我的接管（localStorage 快照，换浏览器丢失可接受）──
const takeovers = ref<Record<string, TakeoverRecord>>({})

// ── 当前选中 ──
const selectedId = ref<string | null>(null)
const selectedDetail = ref<CrisisEventDetail | null>(null)
const detailLoading = ref(false)

// ── 对话输入 / 干预 ──
const replyInput = ref('')
const replySending = ref(false)
const interventionResult = ref('')

const riskColor: Record<string, string> = { 高危: '#ef4444', 中危: '#f59e0b', 低危: '#eab308' }

const takeoverList = computed(() => Object.values(takeovers.value))
const selectedRecord = computed(() =>
  selectedId.value ? takeovers.value[selectedId.value] : null,
)

/** 格式化时间 */
function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ── localStorage 读写（仅快照）──
function loadTakeovers(): Record<string, TakeoverRecord> {
  try {
    const raw = localStorage.getItem(TAKEOVER_KEY)
    return raw ? (JSON.parse(raw) as Record<string, TakeoverRecord>) : {}
  } catch {
    return {}
  }
}
function persist() {
  localStorage.setItem(TAKEOVER_KEY, JSON.stringify(takeovers.value))
}

/** 拉取待接管队列（silent=轮询/切前台时静默刷新，不盖 loading） */
async function loadQueue(silent = false) {
  if (!silent) queueLoading.value = true
  queueError.value = ''
  try {
    const all = await fetchCrisisEvents({ status_filter: 'pending_human' })
    queue.value = all.filter((e) => !takeovers.value[String(e.id)])
  } catch (e) {
    if (!silent) {
      queueError.value = e instanceof ApiError ? e.detail : '加载失败，请稍后再试'
      ElMessage.error(queueError.value)
    }
  } finally {
    queueLoading.value = false
  }
}

/** 接管：先走后端接口（真状态），成功后再写本地快照 */
async function takeOver(event: CrisisEvent) {
  const key = String(event.id)
  if (takeovers.value[key]) return // 已在接管中，不允许再次点击
  try {
    // 后端：pending_human → handling；已被他人接管则 409
    const updated = await takeoverCrisisEvent(event.id, true)
    takeovers.value[key] = { event: updated, takenAt: new Date().toISOString() }
    persist()
    queue.value = queue.value.filter((e) => String(e.id) !== key)
    ElMessage.success(`已接管「${updated.user_nickname || `用户#${updated.user_id}`}」，处理中`)
    await selectTakeover(key)
  } catch (e) {
    // 已被他人接管的场景：直接展示后端 409 文案，并刷新队列
    ElMessage.error(e instanceof ApiError ? e.detail : '接管失败，请稍后再试')
    void loadQueue(true)
  }
}

/** 选中接管记录：拉取最新详情 */
async function selectTakeover(key: string) {
  selectedId.value = key
  selectedDetail.value = null
  interventionResult.value = ''
  detailLoading.value = true
  try {
    selectedDetail.value = await fetchCrisisDetail(Number(key))
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '对话加载失败')
  } finally {
    detailLoading.value = false
  }
}

/** 放弃接管：先释放后端状态（handling → pending_human），成功再移除本地记录 */
async function releaseTakeover(key: string | null) {
  if (!key) return
  try {
    await takeoverCrisisEvent(Number(key), false)
    removeLocalRecord(key)
    ElMessage.success('已释放接管，事件回到待人工')
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '释放失败，请稍后再试')
  }
}

/** 移除本地接管记录（干预完成/释放成功后） */
function removeLocalRecord(key: string) {
  delete takeovers.value[key]
  persist()
  if (selectedId.value === key) {
    selectedId.value = null
    selectedDetail.value = null
  }
  void loadQueue(true)
}

/** 发送运营回复：落库 system 消息并实时推送用户端，成功后追加到本地对话（按 id 去重） */
async function sendReply() {
  const content = replyInput.value.trim()
  const key = selectedId.value
  if (!content || !key || replySending.value) return
  replySending.value = true
  try {
    const msg = await sendCrisisReply(Number(key), content)
    if (selectedDetail.value) {
      // 按 id 去重，避免轮询/重复发送导致重复气泡
      const exists = selectedDetail.value.messages.some((m) => m.id === msg.id)
      if (!exists) selectedDetail.value.messages.push(msg)
    }
    replyInput.value = ''
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '回复发送失败')
  } finally {
    replySending.value = false
  }
}

/** 手动刷新对话（详情不轮询，打开时点这里拿最新） */
async function refreshDetail() {
  if (!selectedId.value) return
  await selectTakeover(selectedId.value)
}

/** 提交干预结果：intervention → resolved 后移出接管（不调 takeover:false，已结束） */
async function submitIntervention() {
  const key = selectedId.value
  if (!key || !interventionResult.value) {
    ElMessage.warning('请先选择干预结果')
    return
  }
  try {
    await markIntervention(Number(key), interventionResult.value, true)
    ElMessage.success('干预结果已记录，事件已处理完成')
    removeLocalRecord(key)
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '提交失败，请稍后再试')
  }
}

/** 角色文案（运营回复以 system 角色落库） */
function roleLabel(role: string): string {
  return role === 'user' ? '用户' : role === 'hina' ? '日奈' : role === 'system' ? '运营' : '系统'
}

const displayMessages = computed(() => selectedDetail.value?.messages ?? [])

let pollTimer: ReturnType<typeof setInterval> | null = null
function onVisibilityChange() {
  if (document.visibilityState === 'visible') void loadQueue(true)
}

onMounted(() => {
  takeovers.value = loadTakeovers()
  void loadQueue()
  pollTimer = setInterval(() => void loadQueue(true), POLL_INTERVAL)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="admin-shell">
    <AdminSidebar active="takeover" />

    <main class="main">
      <header class="page-head">
        <div>
          <h1 class="page-title">
            <el-icon class="title-icon"><Headset /></el-icon>
            人工接管
          </h1>
          <p class="page-sub">点进事件即接管（处理中）· 可同时处理多个用户 · 每 30 秒自动刷新</p>
        </div>
        <el-button type="primary" :icon="Refresh" :loading="queueLoading" @click="loadQueue()">
          刷新队列
        </el-button>
      </header>

      <div class="workspace">
        <!-- 左栏：待接管队列 + 我的接管 -->
        <section class="col-left">
          <div class="panel">
            <h3 class="panel-title">待接管队列</h3>
            <div v-loading="queueLoading" class="panel-body">
              <div v-if="queue.length" class="ev-list">
                <div
                  v-for="ev in queue"
                  :key="ev.id"
                  class="ev-item"
                  @click="takeOver(ev)"
                >
                  <div class="ev-item-head">
                    <span class="ev-nick">{{ ev.user_nickname || `用户#${ev.user_id}` }}</span>
                    <el-tag
                      size="small"
                      :style="{ background: `${riskColor[ev.risk_level] || '#888'}22`, color: riskColor[ev.risk_level] || '#aaa', borderColor: `${riskColor[ev.risk_level] || '#888'}55` }"
                    >
                      {{ ev.risk_level }}
                    </el-tag>
                  </div>
                  <div class="ev-trigger">{{ ev.trigger || '—' }}</div>
                  <div class="ev-time">{{ formatTime(ev.created_at) }}</div>
                </div>
              </div>
              <el-empty v-else :description="queueError || '没有待接管事件'" :image-size="60" />
            </div>
          </div>

          <div class="panel">
            <h3 class="panel-title">
              我的接管
              <span v-if="takeoverList.length" class="badge">{{ takeoverList.length }}</span>
            </h3>
            <div class="panel-body">
              <div v-if="takeoverList.length" class="ev-list">
                <div
                  v-for="rec in takeoverList"
                  :key="rec.event.id"
                  class="ev-item"
                  :class="{ active: selectedId === String(rec.event.id) }"
                  @click="selectTakeover(String(rec.event.id))"
                >
                  <div class="ev-item-head">
                    <span class="ev-nick">{{ rec.event.user_nickname || `用户#${rec.event.user_id}` }}</span>
                    <el-tag size="small" type="warning" effect="plain">处理中</el-tag>
                  </div>
                  <div class="ev-trigger">{{ rec.event.trigger || '—' }}</div>
                  <div class="ev-time">接管于 {{ formatTime(rec.takenAt) }}</div>
                </div>
              </div>
              <el-empty v-else description="尚未接管事件" :image-size="60" />
            </div>
          </div>
        </section>

        <!-- 右区：对话工作台 -->
        <section class="col-right">
          <template v-if="selectedRecord">
            <!-- 事件头 -->
            <div class="chat-head">
              <div class="chat-head-user">
                <span class="user-name">{{ selectedRecord.event.user_nickname || `用户#${selectedRecord.event.user_id}` }}</span>
                <el-tag
                  size="small"
                  :style="{ background: `${riskColor[selectedRecord.event.risk_level] || '#888'}22`, color: riskColor[selectedRecord.event.risk_level] || '#aaa', borderColor: `${riskColor[selectedRecord.event.risk_level] || '#888'}55` }"
                >
                  {{ selectedRecord.event.risk_level }}
                </el-tag>
                <el-tag size="small" type="warning" effect="plain">处理中</el-tag>
                <el-button size="small" text :loading="detailLoading" @click="refreshDetail">
                  刷新对话
                </el-button>
              </div>
              <div class="chat-head-meta">
                事件 #{{ selectedRecord.event.id }} · 会话 {{ selectedRecord.event.conversation_id ?? '—' }} · {{ formatTime(selectedRecord.event.created_at) }}
              </div>
            </div>

            <div v-loading="detailLoading" class="chat-body">
              <!-- 高危摘要 -->
              <div v-if="selectedDetail?.summary?.quick_summary" class="summary-box">
                <span class="summary-label">高危摘要</span>
                <p class="summary-text">{{ selectedDetail.summary.quick_summary }}</p>
              </div>

              <!-- 对话气泡 -->
              <div v-if="displayMessages.length" class="chat-list">
                <div
                  v-for="m in displayMessages"
                  :key="m.id"
                  class="chat-row"
                  :class="{ 'from-user': m.role === 'user', 'from-hina': m.role === 'hina', 'from-system': m.role === 'system' }"
                >
                  <span class="chat-role">{{ roleLabel(m.role) }}</span>
                  <div class="chat-bubble">{{ m.content }}</div>
                  <span class="chat-time">{{ m.time }}</span>
                </div>
              </div>
              <el-empty v-else description="该会话暂无消息" :image-size="60" />
            </div>

            <!-- 操作区：运营回复 + 干预结果 -->
            <div class="chat-ops">
              <div class="reply-row">
                <el-input
                  v-model="replyInput"
                  placeholder="输入回复内容，将实时推送到用户端…"
                  clearable
                  @keyup.enter="sendReply"
                />
                <el-button type="primary" :loading="replySending" :disabled="!replyInput.trim()" @click="sendReply">
                  发送
                </el-button>
              </div>
              <div class="intervene-row">
                <el-select v-model="interventionResult" placeholder="选择干预结果" style="flex: 1">
                  <el-option v-for="opt in INTERVENTION_OPTIONS" :key="opt" :label="opt" :value="opt" />
                </el-select>
                <el-button type="primary" @click="submitIntervention">提交干预结果</el-button>
                <el-button @click="releaseTakeover(selectedId)">放弃接管</el-button>
              </div>
            </div>
          </template>

          <div v-else class="chat-placeholder">
            <el-empty description="从左侧「待接管队列」点击一个事件开始接管" :image-size="90" />
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.admin-shell {
  display: flex;
  min-height: 100vh;
}

/* ---------- 主内容 ---------- */
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: 26px 28px 32px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 600;
  margin: 0;
  letter-spacing: 2px;
  color: var(--nv-text);
}
.title-icon {
  color: var(--nv-amber);
}
.page-sub {
  font-size: 13px;
  color: var(--nv-text-muted);
  margin: 4px 0 0;
}

/* ---------- 工作区 ---------- */
.workspace {
  display: flex;
  gap: 16px;
  flex: 1;
  min-height: 0;
}

.col-left {
  flex: 0 0 300px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.panel {
  background: var(--nv-surface);
  backdrop-filter: blur(14px);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-lg);
  padding: 14px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.panel:first-child {
  flex: 1.2;
}
.panel:nth-child(2) {
  flex: 1;
}
.panel-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--nv-amber);
  letter-spacing: 1px;
  margin: 0 0 10px;
}
.badge {
  background: var(--nv-amber-soft);
  color: var(--nv-amber);
  border-radius: 999px;
  font-size: 11px;
  padding: 0 8px;
  line-height: 18px;
}
.panel-body {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.ev-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ev-item {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}
.ev-item:hover {
  border-color: var(--nv-amber);
  background: rgba(242, 176, 76, 0.07);
}
.ev-item.active {
  border-color: var(--nv-amber);
  background: var(--nv-amber-soft);
}
.ev-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ev-nick {
  font-size: 13px;
  font-weight: 600;
  color: var(--nv-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ev-trigger {
  font-size: 12px;
  color: var(--nv-text-soft);
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ev-time {
  font-size: 11px;
  color: var(--nv-text-muted);
  margin-top: 4px;
}

/* ---------- 对话工作台 ---------- */
.col-right {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--nv-surface);
  backdrop-filter: blur(14px);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.chat-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.chat-head {
  padding: 14px 20px;
  border-bottom: 1px solid var(--nv-border);
}
.chat-head-user {
  display: flex;
  align-items: center;
  gap: 8px;
}
.user-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--nv-text);
}
.chat-head-meta {
  font-size: 12px;
  color: var(--nv-text-muted);
  margin-top: 4px;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  min-height: 0;
}

.summary-box {
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.18);
  border-radius: var(--radius-md);
  padding: 10px 14px;
  margin-bottom: 14px;
}
.summary-label {
  font-size: 12px;
  color: #f87171;
  font-weight: 600;
}
.summary-text {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--nv-text);
  line-height: 1.8;
  white-space: pre-wrap;
}

.chat-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.chat-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-width: 82%;
}
.chat-row.from-user,
.chat-row.from-system {
  align-self: flex-end;
  align-items: flex-end;
}
.chat-row.from-hina {
  align-self: flex-start;
  align-items: flex-start;
}
.chat-role {
  font-size: 11px;
  color: var(--nv-text-muted);
}
.chat-bubble {
  font-size: 13px;
  line-height: 1.7;
  padding: 9px 13px;
  border-radius: var(--radius-md);
  word-break: break-word;
  white-space: pre-wrap;
}
.from-user .chat-bubble {
  background: linear-gradient(135deg, var(--nv-amber), var(--nv-amber-deep));
  color: var(--nv-amber-ink);
  border-bottom-right-radius: 4px;
}
.from-hina .chat-bubble {
  background: rgba(255, 255, 255, 0.06);
  color: var(--nv-text);
  border: 1px solid var(--nv-border);
  border-bottom-left-radius: 4px;
}
.from-system .chat-bubble {
  background: var(--nv-lilac-soft);
  color: var(--nv-lilac);
  border: 1px solid rgba(185, 165, 224, 0.4);
  border-bottom-right-radius: 4px;
}
.chat-time {
  font-size: 11px;
  color: var(--nv-text-muted);
}

/* ---------- 操作区 ---------- */
.chat-ops {
  border-top: 1px solid var(--nv-border);
  padding: 12px 16px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.reply-row {
  display: flex;
  gap: 10px;
}
.intervene-row {
  display: flex;
  gap: 10px;
}
</style>
