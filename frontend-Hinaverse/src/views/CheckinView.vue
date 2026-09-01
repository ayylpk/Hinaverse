<script setup lang="ts">
/**
 * 星历 · 打卡页（月历星星视图）：每日一颗星，有打卡的日子淡淡亮起。
 * 数据源：GET /api/checkin（当前用户全部打卡，接口不变）；
 * 交互：月历切月 → 点某天的星星 → 右侧面板新建/编辑/删除当日打卡（多行输入）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, Plus } from '@element-plus/icons-vue'
// ⚠️ 显式 import ElMessageBox 不走 unplugin 按需样式注入，需手动带样式（否则确认框错位）
import 'element-plus/es/components/message-box/style/css'
import { ApiError } from '@/api/http'
import { createCheckin, deleteCheckin, fetchCheckins, updateCheckinStatus, type Checkin } from '@/api/checkin'

const router = useRouter()

const MAX_CONTENT = 500

const checkins = ref<Checkin[]>([])
const loading = ref(true)
const loadError = ref('')

// 当前浏览的年/月（0-11）+ 选中日期
const viewYear = ref(new Date().getFullYear())
const viewMonth = ref(new Date().getMonth())
const selectedDay = ref<string>(todayStr())

// 新建输入（多行）
const contentInput = ref('')
const submitting = ref(false)

function todayStr(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const monthLabel = computed(() => `${viewYear.value} 年 ${viewMonth.value + 1} 月`)

/** 当月日历格子：null=补位，Date=当天 */
const monthGrid = computed<(Date | null)[]>(() => {
  const first = new Date(viewYear.value, viewMonth.value, 1)
  const startDow = (first.getDay() + 6) % 7 // 周一开头
  const daysInMonth = new Date(viewYear.value, viewMonth.value + 1, 0).getDate()
  const cells: (Date | null)[] = []
  for (let i = 0; i < startDow; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(viewYear.value, viewMonth.value, d))
  return cells
})

/** 有打卡的日期集合（星星亮起） */
const dayKeysWithCheckin = computed<Set<string>>(() => {
  const s = new Set<string>()
  for (const c of checkins.value) s.add(c.date)
  return s
})

/** 按日分组的打卡（当日面板用） */
const checkinsByDay = computed<Map<string, Checkin[]>>(() => {
  const map = new Map<string, Checkin[]>()
  for (const c of checkins.value) {
    const list = map.get(c.date)
    if (list) list.push(c)
    else map.set(c.date, [c])
  }
  return map
})

/** 选中日期的打卡：todo 在前、done 置灰在后 */
const selectedItems = computed(() => {
  const items = checkinsByDay.value.get(selectedDay.value) ?? []
  return [...items.filter((i) => i.status === 'todo'), ...items.filter((i) => i.status === 'done')]
})

/** 当月是否有任何打卡（空态文案判断） */
const hasAnyInMonth = computed(() =>
  monthGrid.value.some((c) => c !== null && dayKeysWithCheckin.value.has(dateKey(c))),
)

const isToday = (d: Date) => dateKey(d) === todayStr()

function dateKey(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function prevMonth() {
  if (viewMonth.value === 0) {
    viewMonth.value = 11
    viewYear.value--
  } else {
    viewMonth.value--
  }
}
function nextMonth() {
  if (viewMonth.value === 11) {
    viewMonth.value = 0
    viewYear.value++
  } else {
    viewMonth.value++
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    checkins.value = await fetchCheckins()
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.detail : '打卡加载失败，请稍后再试'
    ElMessage.error(loadError.value)
  } finally {
    loading.value = false
  }
}

/** 新建（多行输入，前端兜底校验 1..500） */
async function submit() {
  const content = contentInput.value.trim()
  if (!content) {
    ElMessage.warning('写点什么再打卡吧')
    return
  }
  if (content.length > MAX_CONTENT) {
    ElMessage.warning(`内容不能超过 ${MAX_CONTENT} 字`)
    return
  }
  if (submitting.value) return
  submitting.value = true
  try {
    await createCheckin(content, selectedDay.value)
    ElMessage.success('这颗星亮起来了')
    contentInput.value = ''
    await load()
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '创建失败，请稍后再试')
  } finally {
    submitting.value = false
  }
}

/** 打勾切换 done/todo（PATCH） */
async function toggle(item: Checkin) {
  const next = item.status === 'done' ? 'todo' : 'done'
  try {
    await updateCheckinStatus(item.id, next)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '操作失败，请稍后再试')
  }
}

/** 删除：带确认 */
async function remove(item: Checkin) {
  try {
    await ElMessageBox.confirm(
      `确定删除这颗星吗？\n「${item.content.slice(0, 30)}${item.content.length > 30 ? '…' : ''}」`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteCheckin(item.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '删除失败，请稍后再试')
  }
}

onMounted(load)
</script>

<template>
  <div class="checkin-page starfield">
    <!-- 顶部玻璃导航 -->
    <header class="nav-bar">
      <div class="nav-inner">
        <div class="brand">
          <svg class="brand-mark" viewBox="0 0 40 40" aria-hidden="true">
            <rect width="40" height="40" rx="11" fill="rgba(242,176,76,.12)" />
            <path d="M24 8.5a13 13 0 1 0 4 17 10.5 10.5 0 0 1-4-17z" fill="#F2B04C" />
            <circle cx="30" cy="9" r="1.6" fill="#B9A5E0" />
          </svg>
          <div class="brand-text">
            <span class="brand-cn">星历</span>
            <span class="brand-en">CHECK-IN</span>
          </div>
        </div>

        <div class="nav-actions">
          <el-button text @click="router.push({ name: 'Home' })">
            <el-icon class="icon"><ArrowLeft /></el-icon>返回星空
          </el-button>
        </div>
      </div>
    </header>

    <main class="main">
      <div class="checkin-shell">
        <!-- 左：月历星星 -->
        <section class="calendar-panel glass">
          <div class="calendar-head">
            <span class="month-label">{{ monthLabel }}</span>
            <div class="month-nav">
              <el-button circle size="small" text @click="prevMonth">
                <el-icon><ArrowLeft /></el-icon>
              </el-button>
              <el-button circle size="small" text @click="nextMonth">
                <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </div>

          <div class="week-row">
            <span v-for="w in ['一', '二', '三', '四', '五', '六', '日']" :key="w" class="week-cell">{{ w }}</span>
          </div>

          <div v-loading="loading" class="grid">
            <div
              v-for="(cell, i) in monthGrid"
              :key="i"
              class="star-cell"
              :class="{
                blank: cell === null,
                has: cell !== null && dayKeysWithCheckin.has(dateKey(cell)),
                selected: cell !== null && selectedDay === dateKey(cell),
                today: cell !== null && isToday(cell),
              }"
              @click="cell !== null && (selectedDay = dateKey(cell))"
            >
              <template v-if="cell">
                <svg class="star-svg" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    class="star-fill"
                    d="M12 2.5 L14.6 8.7 L21.3 9.2 L16.2 13.7 L17.8 20.5 L12 17 L6.2 20.5 L7.8 13.7 L2.7 9.2 L9.4 8.7 Z"
                  />
                </svg>
                <span class="star-num">{{ cell.getDate() }}</span>
              </template>
            </div>
          </div>

          <p v-if="!hasAnyInMonth && !loading" class="month-empty">这个月还没有亮起来的星</p>
          <p v-if="loadError" class="load-error">{{ loadError }}</p>
        </section>

        <!-- 右：当日打卡 -->
        <section class="list-panel glass">
          <h2 class="panel-title">
            {{ selectedDay }}
            <span v-if="selectedItems.length" class="count-badge">{{ selectedItems.length }} 颗</span>
          </h2>

          <!-- 新建（多行输入 + 0/500 计数） -->
          <div class="compose">
            <el-input
              v-model="contentInput"
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
              resize="none"
              placeholder="写下这一天想坚持或记录的事…"
            />
            <div class="compose-foot">
              <span class="compose-tip">打在 {{ selectedDay }} 这颗星上</span>
              <el-button
                type="primary"
                :icon="Plus"
                :loading="submitting"
                :disabled="!contentInput.trim()"
                @click="submit"
              >
                打卡
              </el-button>
            </div>
          </div>

          <!-- 当日列表 -->
          <div v-if="loadError" class="load-error">{{ loadError }}</div>

          <div v-else-if="selectedItems.length" v-loading="loading" class="items">
            <div v-for="item in selectedItems" :key="item.id" class="item" :class="{ done: item.status === 'done' }">
              <el-checkbox :model-value="item.status === 'done'" @change="toggle(item)" />
              <span class="item-content" :class="{ 'done-text': item.status === 'done' }">{{ item.content }}</span>
              <el-button size="small" text type="danger" @click="remove(item)">删除</el-button>
            </div>
          </div>

          <div v-else v-loading="loading" class="empty-state">
            <svg class="empty-mark" viewBox="0 0 40 40" aria-hidden="true">
              <rect width="40" height="40" rx="11" fill="rgba(242,176,76,.08)" />
              <path d="M20 8a12 12 0 1 0 12 12 12 12 0 0 0-12-12zm0 4a8 8 0 1 1-8 8 8 8 0 0 1 8-8z" fill="rgba(242,176,76,.35)" />
            </svg>
            <p>这一天还没有打卡</p>
            <span>点一颗星，写下一件想坚持的小事</span>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.checkin-page {
  height: 100vh; /* 固定框架：两栏内部各自滚动，内容不撑开页面 */
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

/* 玻璃导航（与 HomeView 同款） */
.nav-bar {
  height: 64px;
  background: rgba(15, 18, 34, 0.72);
  backdrop-filter: blur(16px) saturate(140%);
  -webkit-backdrop-filter: blur(16px) saturate(140%);
  border-bottom: 1px solid var(--nv-border);
  position: sticky;
  top: 0;
  z-index: 10;
  flex-shrink: 0;
}
.nav-inner {
  max-width: 1120px;
  margin: 0 auto;
  height: 100%;
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-mark {
  width: 36px;
  height: 36px;
  filter: drop-shadow(0 0 10px rgba(242, 176, 76, 0.35));
}
.brand-cn {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
  color: var(--nv-text);
  letter-spacing: 3px;
}
.brand-en {
  font-size: 10px;
  letter-spacing: 3px;
  color: var(--nv-text-muted);
}
.nav-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.icon {
  margin-right: 2px;
}

.main {
  flex: 1;
  min-height: 0;
  display: flex;
  justify-content: center;
  padding: 24px 24px 28px;
  position: relative;
  z-index: 1;
}
.checkin-shell {
  width: 100%;
  max-width: 960px;
  display: flex;
  gap: 18px;
  align-items: flex-start;
  min-height: 0;
}

.glass {
  background: var(--nv-surface);
  backdrop-filter: blur(14px);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-lg);
  padding: 20px;
}

/* ---- 月历星星 ---- */
.calendar-panel {
  flex: 0 0 440px;
}
.calendar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.month-label {
  font-size: 16px;
  font-weight: 600;
  color: var(--nv-text);
  letter-spacing: 2px;
}
.month-nav {
  display: flex;
  gap: 4px;
}
.week-row {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  margin-bottom: 6px;
}
.week-cell {
  text-align: center;
  font-size: 12px;
  color: var(--nv-text-muted);
  padding: 4px 0;
}
.grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
  min-height: 300px;
}
.star-cell {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  position: relative;
  border-radius: 10px;
  transition: background 0.2s;
}
.star-cell.blank {
  cursor: default;
}
.star-cell:not(.blank):hover {
  background: rgba(242, 176, 76, 0.08);
}
.star-svg {
  width: 88%;
  height: 88%;
}
/* 无打卡：暗色描边 */
.star-fill {
  fill: rgba(243, 239, 230, 0.03);
  stroke: rgba(243, 239, 230, 0.16);
  stroke-width: 1.2;
  transition: fill 0.25s, stroke 0.25s, filter 0.25s;
}
/* 有打卡：星星淡亮 + 呼吸光晕（引用全局 @keyframes breathe） */
.star-cell.has .star-fill {
  fill: rgba(242, 176, 76, 0.16);
  stroke: rgba(242, 176, 76, 0.5);
  filter: drop-shadow(0 0 6px rgba(242, 176, 76, 0.35));
  animation: breathe 3.2s ease-in-out infinite;
}
.star-cell.selected .star-fill {
  fill: rgba(242, 176, 76, 0.32);
  stroke: var(--nv-amber);
  filter: drop-shadow(0 0 9px rgba(242, 176, 76, 0.5));
}
.star-num {
  position: absolute;
  font-size: 12px;
  color: var(--nv-text-soft);
  pointer-events: none;
}
.star-cell.has .star-num {
  color: var(--nv-amber);
}
.star-cell.today .star-num {
  color: var(--nv-amber);
  font-weight: 700;
}
.month-empty {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--nv-text-muted);
  text-align: center;
}
.load-error {
  margin: 10px 0 0;
  font-size: 12px;
  color: #f87171;
  text-align: center;
}

/* ---- 当日打卡面板 ---- */
.list-panel {
  flex: 1;
  min-width: 0;
  min-height: 0;
  max-height: calc(100vh - 130px); /* 面板封顶，内部滚动，不撑开框架 */
  display: flex;
  flex-direction: column;
}
.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--nv-text);
  letter-spacing: 1px;
  margin: 0 0 14px;
  flex-shrink: 0;
}
.count-badge {
  background: var(--nv-amber-soft);
  color: var(--nv-amber);
  border-radius: 999px;
  font-size: 12px;
  padding: 1px 10px;
}

.compose {
  flex-shrink: 0;
  margin-bottom: 14px;
}
.compose-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}
.compose-tip {
  font-size: 12px;
  color: var(--nv-text-muted);
}

.items {
  flex: 1;
  min-height: 0;
  overflow-y: auto; /* 当日列表内部滚动 */
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--nv-border);
  transition: border-color 0.2s;
}
.item:hover {
  border-color: rgba(242, 176, 76, 0.4);
}
.item.done {
  opacity: 0.55;
}
.item-content {
  flex: 1;
  font-size: 14px;
  color: var(--nv-text);
  word-break: break-word;
  white-space: pre-wrap;
}
.done-text {
  text-decoration: line-through;
  color: var(--nv-text-muted);
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 40px 20px;
  text-align: center;
}
.empty-mark {
  width: 44px;
  height: 44px;
  margin-bottom: 8px;
  filter: drop-shadow(0 0 12px rgba(242, 176, 76, 0.2));
}
.empty-state p {
  margin: 0;
  font-size: 14px;
  color: var(--nv-text-soft);
}
.empty-state span {
  font-size: 12px;
  color: var(--nv-text-muted);
}

/* ---------- 手机适配（≤768px）：固定框架双栏 → 整页滚动单列，桌面零改动 ---------- */
@media (max-width: 768px) {
  .checkin-page {
    height: auto; /* 拆掉 100vh 固定框架（双栏内滚是桌面玩法） */
    min-height: 100dvh;
    overflow: visible;
  }
  .nav-bar {
    height: calc(54px + env(safe-area-inset-top));
    padding-top: env(safe-area-inset-top);
  }
  .nav-inner {
    padding: 0 12px;
  }
  .brand-cn {
    white-space: nowrap;
    letter-spacing: 1px;
  }
  .brand-en {
    display: none;
  }
  .nav-actions {
    gap: 4px;
  }
  .nav-actions a {
    padding: 6px 10px;
    font-size: 12px;
    white-space: nowrap;
  }
  .main {
    padding: 12px 10px calc(24px + env(safe-area-inset-bottom));
  }
  .checkin-shell {
    flex-direction: column; /* 治「周六周日两列被裁」：440px 定宽日历撑爆 360 屏 */
  }
  .glass {
    padding: 14px;
  }
  .calendar-panel {
    flex: none;
    width: 100%;
  }
  .grid {
    min-height: 0; /* 轨道病根：aspect-ratio 星星格 + 300px 高度保底 → 行高反灌列宽，窄屏必溢出 */
  }
  .list-panel {
    max-height: none; /* 面板内滚改随页滚，窄屏两层滚动是灾难 */
  }
  .items {
    overflow: visible;
  }
  .empty-state {
    padding: 32px 20px;
  }
}
</style>
