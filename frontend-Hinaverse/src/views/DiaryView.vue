<script setup lang="ts">
/**
 * 星历 · 日记页（只读）：月历视图 + 有日记的日期打点 + 按日展示。
 * 数据源：GET /api/diary（当前用户全部日记，created_at 倒序）；
 * 前端本地按"归属日"分组（created_at 转本地日期），本期不做 ?month= 服务端分页。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { ApiError } from '@/api/http'
import { fetchDiaries, type Diary } from '@/api/diary'

const router = useRouter()

const diaries = ref<Diary[]>([])
const loading = ref(true)
const loadError = ref('')

// 当前浏览的年/月（0-11）
const viewYear = ref(new Date().getFullYear())
const viewMonth = ref(new Date().getMonth())
// 选中的日期 key（YYYY-MM-DD，本地时区）；默认今天
const selectedDay = ref<string>(dateKey(new Date()))

/** 本地日期 key：YYYY-MM-DD（与后端 date 字段同格式，纯本地时区，不涉 UTC 偏移） */
function dateKey(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 把后端 created_at(ISO) 转本地日期 key */
function diaryKey(iso: string): string {
  return dateKey(new Date(iso))
}

const monthLabel = computed(
  () => `${viewYear.value} 年 ${viewMonth.value + 1} 月`,
)

/** 当月日历格子：null=补位（上月/下月），Date=当天 */
const monthGrid = computed<(Date | null)[]>(() => {
  const first = new Date(viewYear.value, viewMonth.value, 1)
  const startDow = (first.getDay() + 6) % 7 // 周一开头（周一=0）
  const daysInMonth = new Date(viewYear.value, viewMonth.value + 1, 0).getDate()
  const cells: (Date | null)[] = []
  for (let i = 0; i < startDow; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(viewYear.value, viewMonth.value, d))
  return cells
})

/** 有日记的日期集合（YYYY-MM-DD）——打点用 */
const dayKeysWithDiary = computed<Set<string>>(() => {
  const s = new Set<string>()
  for (const d of diaries.value) s.add(diaryKey(d.created_at))
  return s
})

/** 按日分组的日记（同一天多篇全列） */
const diariesByDay = computed<Map<string, Diary[]>>(() => {
  const map = new Map<string, Diary[]>()
  // 接口已按 created_at 倒序 → 分组后每组内自然保持倒序（最新在前）
  for (const d of diaries.value) {
    const k = diaryKey(d.created_at)
    const list = map.get(k)
    if (list) list.push(d)
    else map.set(k, [d])
  }
  return map
})

const selectedDiaries = computed<Diary[]>(() => diariesByDay.value.get(selectedDay.value) ?? [])

/** 选中的日期是否今天（高亮用） */
const isToday = (d: Date) => dateKey(d) === dateKey(new Date())

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
    diaries.value = await fetchDiaries()
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.detail : '日记加载失败，请稍后再试'
    ElMessage.error(loadError.value)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="diary-page starfield">
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
            <span class="brand-en">DIARY</span>
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
      <div class="diary-shell">
        <!-- 左：月历 -->
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
              class="day-cell"
              :class="{
                blank: cell === null,
                has: cell !== null && dayKeysWithDiary.has(dateKey(cell)),
                selected: cell !== null && selectedDay === dateKey(cell),
                today: cell !== null && isToday(cell),
              }"
              @click="cell !== null && (selectedDay = dateKey(cell))"
            >
              <template v-if="cell">
                <span class="day-num">{{ cell.getDate() }}</span>
                <span v-if="dayKeysWithDiary.has(dateKey(cell))" class="dot" />
              </template>
            </div>
          </div>

          <p v-if="loadError" class="load-error">{{ loadError }}</p>
        </section>

        <!-- 右：当日日记 -->
        <section class="list-panel glass">
          <h2 class="list-title">
            {{ selectedDay }}
            <span v-if="selectedDiaries.length" class="count-badge">{{ selectedDiaries.length }} 篇</span>
          </h2>

          <div v-if="selectedDiaries.length" class="diary-list">
            <article v-for="d in selectedDiaries" :key="d.id" class="diary-card">
              <div class="diary-time">{{ new Date(d.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</div>
              <p class="diary-content">{{ d.content }}</p>
            </article>
          </div>

          <div v-else class="empty-state">
            <svg class="empty-mark" viewBox="0 0 40 40" aria-hidden="true">
              <rect width="40" height="40" rx="11" fill="rgba(242,176,76,.08)" />
              <path d="M20 8a12 12 0 1 0 12 12 12 12 0 0 0-12-12zm0 4a8 8 0 1 1-8 8 8 8 0 0 1 8-8z" fill="rgba(242,176,76,.35)" />
            </svg>
            <p>这一天还没有日记</p>
            <span>日奈会在每天结束时，为你说过的那些话留一颗星</span>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.diary-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
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

/* 主区 */
.main {
  flex: 1;
  display: flex;
  justify-content: center;
  padding: 28px 24px 40px;
  position: relative;
  z-index: 1;
}
.diary-shell {
  width: 100%;
  max-width: 960px;
  display: flex;
  gap: 18px;
  align-items: flex-start;
}

.glass {
  background: var(--nv-surface);
  backdrop-filter: blur(14px);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-lg);
  padding: 20px;
}

/* 月历 */
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
  min-height: 280px;
}
.day-cell {
  aspect-ratio: 1;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  cursor: pointer;
  position: relative;
  transition: background 0.2s, border-color 0.2s;
  border: 1px solid transparent;
}
.day-cell.blank {
  cursor: default;
}
.day-cell:not(.blank):hover {
  background: rgba(242, 176, 76, 0.08);
  border-color: var(--nv-amber);
}
.day-num {
  font-size: 14px;
  color: var(--nv-text-soft);
}
.day-cell.today .day-num {
  color: var(--nv-amber);
  font-weight: 700;
}
.day-cell.selected {
  background: var(--nv-amber-soft);
  border-color: var(--nv-amber);
}
.day-cell.selected .day-num {
  color: var(--nv-amber);
  font-weight: 700;
}
.dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--nv-amber);
  box-shadow: 0 0 6px rgba(242, 176, 76, 0.7);
}
.load-error {
  margin: 10px 0 0;
  font-size: 12px;
  color: #f87171;
  text-align: center;
}

/* 当日日记 */
.list-panel {
  flex: 1;
  min-width: 0;
  min-height: 380px;
}
.list-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--nv-text);
  letter-spacing: 1px;
  margin: 0 0 14px;
}
.count-badge {
  background: var(--nv-amber-soft);
  color: var(--nv-amber);
  border-radius: 999px;
  font-size: 12px;
  padding: 1px 10px;
}
.diary-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.diary-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-md);
  padding: 14px 16px;
}
.diary-time {
  font-size: 12px;
  color: var(--nv-amber);
  margin-bottom: 6px;
}
.diary-content {
  margin: 0;
  font-size: 14px;
  line-height: 1.9;
  color: var(--nv-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 70px 20px;
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

/* ---------- 手机适配（≤768px）：双栏并排 → 单列竖排，桌面零改动 ---------- */
@media (max-width: 768px) {
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
  .diary-shell {
    flex-direction: column; /* 治点1：日历 440px 定宽 + 右栏并排把整页撑爆 */
  }
  .glass {
    padding: 14px;
  }
  .calendar-panel {
    flex: none;
    width: 100%;
  }
  .grid {
    min-height: 0; /* 轨道病根：aspect-ratio 格子 + 280px 高度保底 → 行高反灌列宽，窄屏必溢出 */
  }
  .list-panel {
    min-height: 0;
    width: 100%; /* 治点2：日记列表面板被压成 42px 隐形 → 挪到日历下方全宽 */
  }
  .empty-state {
    padding: 32px 20px;
  }
}
</style>
