<script setup lang="ts">
/**
 * 星历 · 打卡页：用户自建记录/打卡（增删改查）。
 * 后端：POST/GET/PATCH/DELETE /api/checkin（JWT，user_id 取登录用户，归属校验在后端）。
 * 交互：新建（内容 + 日期，默认今天）→ 点打勾切换 done/todo → 删除（带确认）→ 空态。
 * 排序：按日期分组（日期倒序），组内未完成(todo)在前、已完成(done)置灰在后。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Plus } from '@element-plus/icons-vue'
import { ApiError } from '@/api/http'
import { createCheckin, deleteCheckin, fetchCheckins, updateCheckinStatus, type Checkin } from '@/api/checkin'

const router = useRouter()

const MAX_CONTENT = 500

const checkins = ref<Checkin[]>([])
const loading = ref(true)
const loadError = ref('')

// 新建表单
const contentInput = ref('')
const dateInput = ref<string>(todayStr())

function todayStr(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 按日期分组（date 倒序），组内 todo 在前 done 在后 */
const grouped = computed(() => {
  const map = new Map<string, Checkin[]>()
  for (const c of checkins.value) {
    const list = map.get(c.date)
    if (list) list.push(c)
    else map.set(c.date, [c])
  }
  // date 倒序（最新在前）
  const keys = [...map.keys()].sort((a, b) => (a < b ? 1 : -1))
  return keys.map((k) => {
    const items = map.get(k)!
    // 组内：todo 在前（保持 id 倒序=后建在前），done 置灰在后
    return {
      date: k,
      todo: items.filter((i) => i.status === 'todo'),
      done: items.filter((i) => i.status === 'done'),
    }
  })
})

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

/** 新建：前端兜底校验（非空 + 长度上限对齐后端 500） */
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
  try {
    await createCheckin(content, dateInput.value || undefined)
    ElMessage.success('打卡成功')
    contentInput.value = ''
    await load()
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '创建失败，请稍后再试')
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
    await ElMessageBox.confirm(`确定删除这条打卡吗？\n「${item.content.slice(0, 30)}${item.content.length > 30 ? '…' : ''}」`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
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
        <!-- 新建打卡 -->
        <section class="compose glass">
          <h2 class="section-title">记一颗星</h2>
          <div class="compose-row">
            <el-input
              v-model="contentInput"
              placeholder="写下今天想坚持或记录的事…"
              maxlength="500"
              show-word-limit
              clearable
              @keyup.enter="submit"
            />
            <el-date-picker
              v-model="dateInput"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择日期（默认今天）"
              class="date-picker"
            />
            <el-button type="primary" :icon="Plus" :disabled="!contentInput.trim()" @click="submit">
              打卡
            </el-button>
          </div>
        </section>

        <!-- 打卡列表 -->
        <section class="list glass">
          <h2 class="section-title">我的打卡</h2>

          <div v-if="loadError" class="load-error">{{ loadError }}</div>

          <div v-else-if="grouped.length" v-loading="loading" class="groups">
            <div v-for="g in grouped" :key="g.date" class="group">
              <h3 class="group-date">{{ g.date }}</h3>

              <div class="items">
                <!-- 未完成：正常样式，排前 -->
                <div v-for="item in g.todo" :key="item.id" class="item">
                  <el-checkbox :model-value="false" @change="toggle(item)" />
                  <span class="item-content">{{ item.content }}</span>
                  <el-button size="small" text type="danger" @click="remove(item)">删除</el-button>
                </div>

                <!-- 已完成：置灰，排后 -->
                <div v-for="item in g.done" :key="item.id" class="item done">
                  <el-checkbox :model-value="true" @change="toggle(item)" />
                  <span class="item-content done-text">{{ item.content }}</span>
                  <el-button size="small" text type="danger" @click="remove(item)">删除</el-button>
                </div>
              </div>
            </div>
          </div>

          <div v-else v-loading="loading" class="empty-state">
            <svg class="empty-mark" viewBox="0 0 40 40" aria-hidden="true">
              <rect width="40" height="40" rx="11" fill="rgba(242,176,76,.08)" />
              <path d="M20 8a12 12 0 1 0 12 12 12 12 0 0 0-12-12zm0 4a8 8 0 1 1-8 8 8 8 0 0 1 8-8z" fill="rgba(242,176,76,.35)" />
            </svg>
            <p>还没有打卡记录</p>
            <span>从上面写下第一件想坚持的事开始</span>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.checkin-page {
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

.main {
  flex: 1;
  display: flex;
  justify-content: center;
  padding: 28px 24px 40px;
  position: relative;
  z-index: 1;
}
.checkin-shell {
  width: 100%;
  max-width: 720px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.glass {
  background: var(--nv-surface);
  backdrop-filter: blur(14px);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--nv-amber);
  letter-spacing: 1px;
  margin: 0 0 14px;
}

/* 新建区 */
.compose-row {
  display: flex;
  gap: 10px;
  align-items: center;
}
.date-picker {
  width: 170px;
  flex-shrink: 0;
}

/* 列表 */
.groups {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.group-date {
  font-size: 13px;
  font-weight: 600;
  color: var(--nv-text-soft);
  margin: 0 0 8px;
  letter-spacing: 1px;
}
.items {
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

.load-error {
  font-size: 13px;
  color: #f87171;
  text-align: center;
  padding: 30px 0;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 50px 20px;
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
</style>
