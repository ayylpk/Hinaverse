<script setup lang="ts">
/**
 * 运营大盘（统计页，/api/admin）：
 *   指标卡六枚 → GET /stats（60s 静默轮询 + 切回前台即刷）
 *   7 日趋势 / 危机分布 → echarts（按需引入 core+bar/line，canvas）
 *   用户表（搜索/分页）→ GET /users；点行开抽屉
 *   抽屉 → GET /users/{id}/detail 秒开 + GET /users/{id}/portrait 懒加载
 *          （画像跨服务最坏 3s，拆开加载：AgentMemory 挂了只空画像栏）
 * 配色沿用夜航 token（--nv-*），图表色与危机页 tag 同源（CRISIS_RISK_COLOR）。
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { DataAnalysis, Refresh, Search } from '@element-plus/icons-vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import AdminSidebar from '@/components/AdminSidebar.vue'
import { ApiError } from '@/api/http'
import { CRISIS_RISK_COLOR, CRISIS_STATUS_TEXT, type CrisisMessage } from '@/api/crisis'
import {
  fetchAdminStats,
  fetchAdminUsers,
  fetchUserDetail,
  fetchUserPortrait,
  type AdminStats,
  type AdminUser,
  type AdminUserDetail,
} from '@/api/admin'

echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

// ── 夜航配色（echarts 拿不了 CSS 变量，常量表与 style.css 对齐） ──
const C = {
  amber: '#F2B04C',
  lilac: '#B9A5E0',
  red: '#F87171',
  green: '#4ADE80',
  textSoft: '#9AA3B8',
  splitLine: 'rgba(255,255,255,0.06)',
  axisLine: 'rgba(255,255,255,0.14)',
  tooltipBg: '#1C2438',
}

// ── 大盘数据 ──
const stats = ref<AdminStats | null>(null)
const statsLoading = ref(false)

/** 指标卡定义（值从 stats 现取；tone 决定数字颜色：红=需要行动，绿=状态良好） */
const cardDefs = computed(() => {
  const c = stats.value?.cards
  return [
    { label: '总用户', value: c?.total_users ?? '—', sub: '含管理员', tone: '' },
    { label: '今日新增', value: c?.new_users_today ?? '—', sub: `当日 0 点起（北京时间）`, tone: '' },
    { label: '近 7 日活跃', value: c?.active_users_7d ?? '—', sub: '发过言的去重用户', tone: '' },
    { label: '近 7 日消息', value: c?.messages_7d ?? '—', sub: '含日奈与运营回复', tone: '' },
    { label: '未关闭危机', value: c?.open_crises ?? '—', sub: '待人工 / 安抚中 / 处理中', tone: (c?.open_crises ?? 0) > 0 ? 'tone-red' : 'tone-green' },
    { label: '当前在线', value: c?.online_users ?? '—', sub: 'WS 实时连接数', tone: (c?.online_users ?? 0) > 0 ? 'tone-green' : '' },
  ]
})

async function loadStats(silent = false) {
  if (!silent) statsLoading.value = true
  try {
    stats.value = await fetchAdminStats()
    await nextTick() // 卡片/容器先渲染，再画图
    renderTrend()
    renderDist()
  } catch (e) {
    if (!silent) ElMessage.error(e instanceof ApiError ? e.detail : '大盘加载失败')
  } finally {
    statsLoading.value = false
  }
}

// ── echarts：趋势（双轴，消息柱 + 新增/危机线）与危机分布（风险 × 状态堆叠柱） ──
const trendRef = ref<HTMLDivElement>()
const distRef = ref<HTMLDivElement>()
let chartTrend: echarts.EChartsType | null = null
let chartDist: echarts.EChartsType | null = null

const TOOLTIP = {
  trigger: 'axis' as const,
  backgroundColor: C.tooltipBg,
  borderColor: C.axisLine,
  textStyle: { color: '#E6E9F2', fontSize: 12 },
}
const AXIS_LABEL = { color: C.textSoft, fontSize: 11 }

function renderTrend() {
  const el = trendRef.value
  const trend = stats.value?.trend
  if (!el || !trend) return
  if (!chartTrend) chartTrend = echarts.init(el)
  chartTrend.setOption({
    tooltip: TOOLTIP,
    legend: { top: 0, right: 0, textStyle: { color: C.textSoft, fontSize: 12 }, itemWidth: 14, itemHeight: 8 },
    grid: { left: 40, right: 34, top: 34, bottom: 24 },
    xAxis: {
      type: 'category',
      data: trend.map((p) => p.date.slice(5)), // MM-DD
      axisLabel: AXIS_LABEL,
      axisLine: { lineStyle: { color: C.axisLine } },
    },
    yAxis: [
      { type: 'value', minInterval: 1, axisLabel: AXIS_LABEL, splitLine: { lineStyle: { color: C.splitLine } } },
      { type: 'value', minInterval: 1, axisLabel: AXIS_LABEL, splitLine: { show: false } },
    ],
    series: [
      { name: '消息数', type: 'bar', data: trend.map((p) => p.messages), barWidth: 16, itemStyle: { color: C.amber, borderRadius: [3, 3, 0, 0] } },
      { name: '新增用户', type: 'line', yAxisIndex: 1, data: trend.map((p) => p.new_users), smooth: true, symbolSize: 5, lineStyle: { color: C.lilac }, itemStyle: { color: C.lilac } },
      { name: '危机事件', type: 'line', yAxisIndex: 1, data: trend.map((p) => p.crises), smooth: true, symbolSize: 5, lineStyle: { color: C.red }, itemStyle: { color: C.red } },
    ],
  })
}

/** 分布堆叠柱：风险等级固定三档，状态按处理流程排（颜色与危机页 status 胶囊同源） */
const DIST_RISKS = ['高危', '中危', '低危']
const DIST_STATUSES = [
  { key: 'pending_human', label: '待人工', color: C.red },
  { key: 'comforting', label: '安抚中', color: C.lilac },
  { key: 'handling', label: '处理中', color: C.amber },
  { key: 'resolved', label: '已处理', color: C.green },
]

function renderDist() {
  const el = distRef.value
  const dist = stats.value?.crisis_dist
  if (!el || !dist) return
  if (!chartDist) chartDist = echarts.init(el)
  const countOf = (risk: string, status: string) =>
    dist.find((d) => d.risk_level === risk && d.status === status)?.count ?? 0
  chartDist.setOption({
    tooltip: { ...TOOLTIP, axisPointer: { type: 'shadow' } },
    legend: { top: 0, right: 0, textStyle: { color: C.textSoft, fontSize: 12 }, itemWidth: 14, itemHeight: 8 },
    grid: { left: 40, right: 16, top: 34, bottom: 24 },
    xAxis: {
      type: 'category',
      data: DIST_RISKS,
      axisLabel: { ...AXIS_LABEL, fontSize: 12 },
      axisLine: { lineStyle: { color: C.axisLine } },
    },
    yAxis: { type: 'value', minInterval: 1, axisLabel: AXIS_LABEL, splitLine: { lineStyle: { color: C.splitLine } } },
    series: DIST_STATUSES.map((s) => ({
      name: s.label,
      type: 'bar' as const,
      stack: 'total',
      barWidth: 36,
      itemStyle: { color: s.color },
      data: DIST_RISKS.map((r) => countOf(r, s.key)),
    })),
  })
}

function onResize() {
  chartTrend?.resize()
  chartDist?.resize()
}

// ── 用户表 ──
const users = ref<AdminUser[]>([])
const usersLoading = ref(false)
const q = ref('')
const page = ref(1)
const total = ref(0)
const PAGE_SIZE = 20

async function loadUsers() {
  usersLoading.value = true
  try {
    const data = await fetchAdminUsers({ q: q.value || undefined, page: page.value, size: PAGE_SIZE })
    users.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '用户列表加载失败')
  } finally {
    usersLoading.value = false
  }
}

function searchUsers() {
  page.value = 1 // 搜索后回到第一页（沿用旧页码会看不到命中结果）
  void loadUsers()
}

// ── 用户详情抽屉（资料/消息/危机史 + 画像懒加载） ──
const drawerVisible = ref(false)
const detail = ref<AdminUserDetail | null>(null)
const detailLoading = ref(false)
const portrait = ref<string | null | undefined>(undefined) // undefined=加载中/未加载，null=确无画像
const portraitLoading = ref(false)

function openUser(row: AdminUser) {
  drawerVisible.value = true
  detail.value = null
  portrait.value = undefined
  detailLoading.value = true
  portraitLoading.value = true
  fetchUserDetail(row.id)
    .then((d) => (detail.value = d))
    .catch((e) => ElMessage.error(e instanceof ApiError ? e.detail : '详情加载失败'))
    .finally(() => (detailLoading.value = false))
  // 与详情并行、互不等待：画像跨服务最坏 3s，失败只影响画像栏空态
  fetchUserPortrait(row.id)
    .then((p) => (portrait.value = p.portrait))
    .catch(() => (portrait.value = null))
    .finally(() => (portraitLoading.value = false))
}

/** 格式化后端 ISO 时间为「YYYY-MM-DD HH:mm」（与危机页同款口径，两页各留一份不跨页耦合） */
function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 消息气泡角色文案（与危机页一致：operator=运营代日奈发言，归日奈侧） */
function roleLabel(m: CrisisMessage): string {
  if (m.role === 'user') return '用户'
  if (m.role === 'hina') return '日奈'
  if (m.role === 'operator') return '运营'
  return '系统'
}

// ── 实时性：大盘 60s 静默轮询 + 切回前台即刷（表格局部不轮，操作驱动） ──
const POLL_INTERVAL = 60_000
let pollTimer: ReturnType<typeof setInterval> | null = null

function onVisibilityChange() {
  if (document.visibilityState === 'visible') void loadStats(true)
}

onMounted(() => {
  void loadStats()
  void loadUsers()
  pollTimer = setInterval(() => void loadStats(true), POLL_INTERVAL)
  document.addEventListener('visibilitychange', onVisibilityChange)
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  window.removeEventListener('resize', onResize)
  chartTrend?.dispose()
  chartDist?.dispose()
  chartTrend = null
  chartDist = null
})
</script>

<template>
  <div class="admin-shell">
    <AdminSidebar active="dashboard" />

    <main class="main">
      <header class="page-head">
        <div>
          <h1 class="page-title">运营大盘</h1>
          <p class="page-sub">用户 / 对话 / 危机全景 · 数据每 60 秒自动刷新</p>
        </div>
        <el-button type="primary" :icon="Refresh" :loading="statsLoading" @click="loadStats()">刷新</el-button>
      </header>

      <!-- 指标卡 -->
      <section class="cards">
        <div v-for="c in cardDefs" :key="c.label" class="card">
          <div class="card-label">{{ c.label }}</div>
          <div class="card-value" :class="c.tone">{{ c.value }}</div>
          <div class="card-sub">{{ c.sub }}</div>
        </div>
      </section>

      <!-- 图表 -->
      <section class="charts" v-loading="statsLoading">
        <div class="chart-card">
          <h3 class="chart-title"><el-icon><DataAnalysis /></el-icon> 近 7 日趋势</h3>
          <div ref="trendRef" class="chart"></div>
        </div>
        <div class="chart-card">
          <h3 class="chart-title"><el-icon><DataAnalysis /></el-icon> 危机分布（全历史）</h3>
          <div ref="distRef" class="chart"></div>
        </div>
      </section>

      <!-- 用户表 -->
      <header class="section-head">
        <h2 class="section-title">用户</h2>
        <div class="user-tools">
          <el-input
            v-model="q"
            :prefix-icon="Search"
            placeholder="搜用户名 / 昵称"
            clearable
            class="search-input"
            @keyup.enter="searchUsers"
            @clear="searchUsers"
          />
          <el-button @click="searchUsers">搜索</el-button>
        </div>
      </header>

      <div class="table-card">
        <el-table
          :data="users"
          v-loading="usersLoading"
          style="width: 100%"
          :row-class-name="() => 'clickable-row'"
          @row-click="(row: any) => openUser(row as AdminUser)"
        >
          <el-table-column prop="id" label="ID" width="64" />
          <el-table-column label="用户" min-width="150">
            <template #default="{ row }">
              <span class="user-name">{{ row.nickname || row.username }}</span>
              <span class="user-sub">@{{ row.username }}</span>
            </template>
          </el-table-column>
          <el-table-column label="角色" width="92">
            <template #default="{ row }">
              <el-tag size="small" :type="row.role === 'admin' ? 'warning' : 'info'" effect="plain">
                {{ row.role === 'admin' ? '管理员' : '用户' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="注册时间" width="150">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="末次发言" width="150">
            <template #default="{ row }">{{ formatTime(row.last_active) }}</template>
          </el-table-column>
          <el-table-column prop="msg_count" label="发言数" width="86" align="right" />
          <el-table-column label="危机数" width="86" align="right">
            <template #default="{ row }">
              <span :class="{ 'crisis-hot': row.crisis_count > 0 }">{{ row.crisis_count }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="88" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click.stop="openUser(row as AdminUser)">详情</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="没有匹配的用户" :image-size="70" />
          </template>
        </el-table>
        <div class="pager">
          <el-pagination
            v-model:current-page="page"
            background
            layout="total, prev, pager, next"
            :total="total"
            :page-size="PAGE_SIZE"
            @current-change="loadUsers"
          />
        </div>
      </div>
    </main>

    <!-- 用户详情抽屉 -->
    <el-drawer v-model="drawerVisible" size="560px" :title="detail ? `用户 @${detail.user.username}` : '用户详情'">
      <div v-loading="detailLoading" class="drawer-body">
        <template v-if="detail">
          <!-- 资料 -->
          <section class="block">
            <h3 class="block-title">用户资料</h3>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="昵称">{{ detail.user.nickname || '—' }}</el-descriptions-item>
              <el-descriptions-item label="角色">{{ detail.user.role === 'admin' ? '管理员' : '用户' }}</el-descriptions-item>
              <el-descriptions-item label="注册时间">{{ formatTime(detail.user.created_at) }}</el-descriptions-item>
              <el-descriptions-item label="末次发言">{{ formatTime(detail.user.last_active) }}</el-descriptions-item>
              <el-descriptions-item label="发言数">{{ detail.user.msg_count }}</el-descriptions-item>
              <el-descriptions-item label="危机事件">{{ detail.user.crisis_count }}</el-descriptions-item>
            </el-descriptions>
          </section>

          <!-- 画像（懒加载：跨服务，失败/没有只空这一栏） -->
          <section class="block">
            <h3 class="block-title">
              用户画像
              <span class="block-hint">来自 AgentMemory · 服务端缓存 5 分钟</span>
            </h3>
            <div v-if="portraitLoading" class="portrait-loading">画像加载中…</div>
            <p v-else-if="portrait" class="portrait-text">{{ portrait }}</p>
            <el-empty
              v-else
              :image-size="52"
              description="暂无画像 —— 记忆管线按天消化可能尚未生成，或记忆服务当前不可达"
            />
          </section>

          <!-- 最近消息 -->
          <section class="block">
            <h3 class="block-title">最近对话（跨会话最多 20 条，只读）</h3>
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
            <el-empty v-else description="该用户暂无消息记录" :image-size="60" />
          </section>

          <!-- 危机史 -->
          <section class="block">
            <h3 class="block-title">危机事件史</h3>
            <div v-if="detail.crises.length" class="crisis-list">
              <div v-for="ev in detail.crises" :key="ev.id" class="crisis-row">
                <el-tag
                  size="small"
                  :style="{ background: `${CRISIS_RISK_COLOR[ev.risk_level] || '#888'}22`, color: CRISIS_RISK_COLOR[ev.risk_level] || '#aaa', borderColor: `${CRISIS_RISK_COLOR[ev.risk_level] || '#888'}55` }"
                >
                  {{ ev.risk_level }}
                </el-tag>
                <span class="status-text" :class="`status-${ev.status}`">{{ CRISIS_STATUS_TEXT[ev.status] || ev.status }}</span>
                <span class="crisis-time">{{ formatTime(ev.created_at) }}</span>
                <span v-if="ev.intervention_result" class="crisis-intervene">{{ ev.intervention_result }}</span>
              </div>
            </div>
            <el-empty v-else description="无危机事件记录" :image-size="52" />
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

/* ---------- 指标卡 ---------- */
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}
.card {
  background: var(--nv-surface);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-lg);
  padding: 16px 18px 14px;
}
.card-label {
  font-size: 12px;
  letter-spacing: 1px;
  color: var(--nv-text-muted);
}
.card-value {
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 600;
  color: var(--nv-text);
  line-height: 1.35;
  font-variant-numeric: tabular-nums;
}
.card-value.tone-red {
  color: var(--nv-red, #f87171);
}
.card-value.tone-green {
  color: var(--nv-green, #4ade80);
}
.card-sub {
  font-size: 11px;
  color: var(--nv-text-muted);
}

/* ---------- 图表 ---------- */
.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 26px;
}
@media (max-width: 1100px) {
  .charts {
    grid-template-columns: 1fr;
  }
}
.chart-card {
  background: var(--nv-surface);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-lg);
  padding: 14px 16px 10px;
}
.chart-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 6px;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 1px;
  color: var(--nv-amber);
}
.chart {
  height: 260px;
}

/* ---------- 用户表 ---------- */
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.section-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 2px;
  color: var(--nv-text);
}
.user-tools {
  display: flex;
  gap: 10px;
}
.search-input {
  width: 220px;
}

.table-card {
  background: var(--nv-surface);
  backdrop-filter: blur(14px);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-lg);
  padding: 6px 14px 12px;
}
:deep(.clickable-row) {
  cursor: pointer;
}
.user-name {
  color: var(--nv-text);
}
.user-sub {
  margin-left: 8px;
  font-size: 12px;
  color: var(--nv-text-muted);
}
.crisis-hot {
  color: #f87171;
  font-weight: 600;
}
.pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 12px;
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
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--nv-amber);
  margin: 0 0 10px;
  letter-spacing: 1px;
}
.block-hint {
  font-size: 11px;
  font-weight: 400;
  color: var(--nv-text-muted);
  letter-spacing: 0;
}

.portrait-loading {
  font-size: 13px;
  color: var(--nv-text-muted);
  padding: 12px 0;
}
.portrait-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.85;
  color: var(--nv-text);
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--nv-bubble-hina, rgba(255, 255, 255, 0.05));
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-md);
  padding: 12px 14px;
}

/* 对话气泡（危机页同款样式，两页各自 scoped，改动时记得同步） */
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

/* 危机史行 */
.crisis-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.crisis-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--nv-text-soft, #c6cbd9);
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
}
.crisis-time {
  color: var(--nv-text-muted);
}
.crisis-intervene {
  margin-left: auto;
  color: var(--nv-text-muted);
}
.status-text {
  font-size: 12px;
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
</style>
