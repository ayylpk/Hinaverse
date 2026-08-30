<script setup lang="ts">
/**
 * 危机事件列表（运营台主页）：筛选 / 列表 / 详情抽屉 / 标记干预。
 * 全部走真实接口：GET /api/crisis、GET /api/crisis/{id}、POST /api/crisis/{id}/intervention。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Tickets } from '@element-plus/icons-vue'
import AdminSidebar from '@/components/AdminSidebar.vue'
import { ApiError } from '@/api/http'
import {
  fetchCrisisEvents,
  fetchCrisisDetail,
  markIntervention,
  INTERVENTION_OPTIONS,
  type CrisisEvent,
  type CrisisEventDetail,
  type CrisisMessage,
} from '@/api/crisis'

// ── 列表 ──
const events = ref<CrisisEvent[]>([])
const loading = ref(false)
const loadError = ref('')

// ── 筛选 ──
const statusFilter = ref('')
const riskFilter = ref('')
const STATUS_OPTIONS = [
  { label: '待人工', value: 'pending_human' },
  { label: '安抚中', value: 'comforting' },
  { label: '处理中', value: 'handling' },
  { label: '已处理', value: 'resolved' },
]
const RISK_OPTIONS = [
  { label: '高危', value: '高危' },
  { label: '中危', value: '中危' },
  { label: '低危', value: '低危' },
]

// ── 详情抽屉 ──
const drawerVisible = ref(false)
const detail = ref<CrisisEventDetail | null>(null)
const detailLoading = ref(false)
const interventionResult = ref('')

const statusText: Record<string, string> = {
  pending_human: '待人工',
  comforting: '安抚中',
  handling: '处理中',
  resolved: '已处理',
}

const riskColor: Record<string, string> = {
  高危: '#ef4444',
  中危: '#f59e0b',
  低危: '#eab308',
}

/** 格式化后端 ISO 时间为「YYYY-MM-DD HH:mm」 */
function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 拉取列表（silent=轮询/切前台静默刷新，不盖 loading） */
async function loadEvents(silent = false) {
  if (!silent) loading.value = true
  loadError.value = ''
  try {
    events.value = await fetchCrisisEvents({
      status_filter: statusFilter.value || undefined,
      risk_level: riskFilter.value || undefined,
    })
  } catch (e) {
    if (!silent) {
      loadError.value = e instanceof ApiError ? e.detail : '加载失败，请稍后再试'
      ElMessage.error(loadError.value)
    }
  } finally {
    loading.value = false
  }
}

/** 打开详情抽屉：拉事件 + 会话最近对话 */
async function openDetail(row: CrisisEvent) {
  drawerVisible.value = true
  detail.value = null
  detailLoading.value = true
  interventionResult.value = ''
  try {
    detail.value = await fetchCrisisDetail(row.id)
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

/** 标记干预结果：选择即提交（resolved=true 落库为已处理） */
async function submitIntervention() {
  if (!detail.value || !interventionResult.value) {
    ElMessage.warning('请先选择干预结果')
    return
  }
  try {
    await markIntervention(detail.value.id, interventionResult.value, true)
    ElMessage.success('干预结果已记录')
    drawerVisible.value = false
    await loadEvents()
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '提交失败，请稍后再试')
  }
}

/** 消息气泡角色文案 */
function roleLabel(m: CrisisMessage): string {
  return m.role === 'user' ? '用户' : m.role === 'hina' ? '日奈' : '系统'
}

// ── 实时性：30s 轮询 + 页面切回前台立即刷新（静默，不盖 loading）──
const POLL_INTERVAL = 30_000
let pollTimer: ReturnType<typeof setInterval> | null = null

function onVisibilityChange() {
  if (document.visibilityState === 'visible') void loadEvents(true)
}

onMounted(() => {
  void loadEvents()
  pollTimer = setInterval(() => void loadEvents(true), POLL_INTERVAL)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="admin-shell">
    <!-- 左侧窄边栏 -->
    <AdminSidebar active="crisis" />

    <!-- 主内容区 -->
    <main class="main">
      <header class="page-head">
        <div>
          <h1 class="page-title">危机事件</h1>
          <p class="page-sub">心理危机干预闭环 · 待人工与安抚中的事件需要优先处理</p>
        </div>
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadEvents()">
          刷新
        </el-button>
      </header>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-select v-model="statusFilter" placeholder="全部状态" clearable class="filter-select" @change="loadEvents()">
          <el-option v-for="s in STATUS_OPTIONS" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-select v-model="riskFilter" placeholder="全部等级" clearable class="filter-select" @change="loadEvents()">
          <el-option v-for="r in RISK_OPTIONS" :key="r.value" :label="r.label" :value="r.value" />
        </el-select>
        <span class="count-hint">共 {{ events.length }} 条</span>
      </div>

      <!-- 列表 -->
      <div class="table-card">
        <el-table
          :data="events"
          v-loading="loading"
          style="width: 100%"
          @row-click="(row: any) => openDetail(row)"
          :row-class-name="() => 'clickable-row'"
        >
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column label="用户昵称" width="130">
            <template #default="{ row }">
              {{ row.user_nickname || `用户#${row.user_id}` }}
            </template>
          </el-table-column>
          <el-table-column label="风险等级" width="100">
            <template #default="{ row }">
              <el-tag
                :style="{ background: `${riskColor[row.risk_level] || '#888'}22`, color: riskColor[row.risk_level] || '#aaa', borderColor: `${riskColor[row.risk_level] || '#888'}55` }"
              >
                {{ row.risk_level }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <span class="status-text" :class="`status-${row.status}`">
                {{ statusText[row.status] || row.status }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="trigger" label="触发摘要" min-width="220" show-overflow-tooltip />
          <el-table-column label="创建时间" width="160">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click.stop="openDetail(row as CrisisEvent)">详情</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :description="loadError || '暂无危机事件'" :image-size="80" />
          </template>
        </el-table>
      </div>
    </main>

    <!-- 事件详情抽屉 -->
    <el-drawer v-model="drawerVisible" size="560px" :title="detail ? `危机事件 #${detail.id}` : '事件详情'">
      <div v-loading="detailLoading" class="drawer-body">
        <template v-if="detail">
          <!-- 事件字段 -->
          <section class="block">
            <h3 class="block-title">
              <el-icon><Tickets /></el-icon> 事件信息
            </h3>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="事件 ID">{{ detail.id }}</el-descriptions-item>
              <el-descriptions-item label="用户昵称">{{ detail.user_nickname || `用户#${detail.user_id}` }}</el-descriptions-item>
              <el-descriptions-item label="用户 ID">{{ detail.user_id }}</el-descriptions-item>
              <el-descriptions-item label="会话 ID">{{ detail.conversation_id ?? '—' }}</el-descriptions-item>
              <el-descriptions-item label="风险等级">
                <el-tag
                  :style="{ background: `${riskColor[detail.risk_level] || '#888'}22`, color: riskColor[detail.risk_level] || '#aaa', borderColor: `${riskColor[detail.risk_level] || '#888'}55` }"
                >
                  {{ detail.risk_level }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="状态">{{ statusText[detail.status] || detail.status }}</el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
              <el-descriptions-item label="解决时间">{{ formatTime(detail.resolved_at) }}</el-descriptions-item>
            </el-descriptions>
            <div class="field-row">
              <span class="field-label">触发原因</span>
              <p class="field-value">{{ detail.trigger || '—' }}</p>
            </div>
            <div class="field-row">
              <span class="field-label">关键原句</span>
              <p class="field-value signal">{{ detail.signal || '—' }}</p>
            </div>
            <div v-if="detail.comfort_log" class="field-row">
              <span class="field-label">安抚记录</span>
              <p class="field-value">{{ detail.comfort_log }}</p>
            </div>
            <div v-if="detail.intervention_result" class="field-row">
              <span class="field-label">干预结果</span>
              <p class="field-value">{{ detail.intervention_result }}</p>
            </div>
          </section>

          <!-- 高危摘要 -->
          <section v-if="detail.summary?.quick_summary" class="block summary-block">
            <h3 class="block-title">高危摘要</h3>
            <p class="summary-text">{{ detail.summary.quick_summary }}</p>
          </section>

          <!-- 会话最近对话 -->
          <section class="block">
            <h3 class="block-title">该会话最近对话（最多 20 条，只读）</h3>
            <div v-if="detail.messages.length" class="chat-list">
              <div
                v-for="m in detail.messages"
                :key="m.id"
                class="chat-row"
                :class="m.role === 'user' ? 'from-user' : 'from-hina'"
              >
                <span class="chat-role">{{ roleLabel(m) }}</span>
                <div class="chat-bubble">{{ m.content }}</div>
                <span class="chat-time">{{ m.time }}</span>
              </div>
            </div>
            <el-empty v-else description="该会话暂无消息记录" :image-size="60" />
          </section>

          <!-- 标记干预 -->
          <section class="block intervene-block">
            <h3 class="block-title">标记干预结果</h3>
            <div class="intervene-row">
              <el-select v-model="interventionResult" placeholder="选择干预结果" style="flex: 1">
                <el-option v-for="opt in INTERVENTION_OPTIONS" :key="opt" :label="opt" :value="opt" />
              </el-select>
              <el-button type="primary" @click="submitIntervention">提交</el-button>
            </div>
            <p class="intervene-hint">提交后事件状态将变为「已处理」，并记录处理时间。</p>
          </section>
        </template>
      </div>
    </el-drawer>
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
  padding: 30px 34px 40px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 18px;
}
.page-title {
  font-family: var(--font-display);
  font-size: 26px;
  font-weight: 600;
  margin: 0;
  letter-spacing: 2px;
  color: var(--nv-text);
}
.page-sub {
  font-size: 13px;
  color: var(--nv-text-muted);
  margin: 4px 0 0;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.filter-select {
  width: 160px;
}
.count-hint {
  font-size: 12px;
  color: var(--nv-text-muted);
}

.table-card {
  background: var(--nv-surface);
  backdrop-filter: blur(14px);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-lg);
  padding: 6px 14px;
  overflow: hidden;
}
:deep(.clickable-row) {
  cursor: pointer;
}

.status-text {
  font-size: 13px;
  padding: 2px 10px;
  border-radius: 999px;
  display: inline-block;
}
.status-pending_human {
  color: #f87171;
  background: rgba(248, 113, 113, 0.12);
}
.status-comforting {
  color: var(--nv-lilac);
  background: var(--nv-lilac-soft);
}
.status-handling {
  color: var(--nv-amber);
  background: var(--nv-amber-soft);
}
.status-resolved {
  color: #4ade80;
  background: rgba(74, 222, 128, 0.1);
}

/* ---------- 抽屉 ---------- */
.drawer-body {
  padding: 0 4px;
}
.block {
  margin-bottom: 22px;
}
.block-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--nv-amber);
  margin: 0 0 10px;
  letter-spacing: 1px;
}

.field-row {
  margin-top: 12px;
}
.field-label {
  display: block;
  font-size: 12px;
  color: var(--nv-text-muted);
  margin-bottom: 4px;
}
.field-value {
  margin: 0;
  font-size: 13px;
  color: var(--nv-text);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.field-value.signal {
  color: var(--nv-amber);
  background: var(--nv-amber-soft);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
}

.summary-block {
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.18);
  border-radius: var(--radius-md);
  padding: 12px 16px;
}
.summary-text {
  margin: 0;
  font-size: 13px;
  color: var(--nv-text);
  line-height: 1.8;
  white-space: pre-wrap;
}

/* 对话气泡 */
.chat-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 380px;
  overflow-y: auto;
  padding-right: 4px;
}
.chat-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-width: 86%;
}
.chat-row.from-user {
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
  background: var(--nv-bubble-hina, rgba(255, 255, 255, 0.06));
  color: var(--nv-text);
  border: 1px solid var(--nv-border);
  border-bottom-left-radius: 4px;
}
.chat-time {
  font-size: 11px;
  color: var(--nv-text-muted);
}

/* 干预区 */
.intervene-block {
  border-top: 1px solid var(--nv-border);
  padding-top: 16px;
}
.intervene-row {
  display: flex;
  gap: 10px;
}
.intervene-hint {
  font-size: 12px;
  color: var(--nv-text-muted);
  margin: 8px 0 0;
}
</style>
