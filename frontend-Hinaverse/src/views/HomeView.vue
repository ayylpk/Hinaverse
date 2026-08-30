<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
// ⚠️ 显式 import ElMessageBox 不走 unplugin 按需样式注入（resolver 只管模板组件/自动导入），
// 必须手动带组件样式，否则 message-box 裸奔错位（确认框跑到屏幕左侧被遮挡）。
import 'element-plus/es/components/message-box/style/css'
import { Calendar, Tickets } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import ChatWindow from '@/components/ChatWindow.vue'
import ProfileDialog from '@/components/ProfileDialog.vue'

const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()
const profileVisible = ref(false)

onMounted(async () => {
  // 恢复最新资料（昵称/头像可能被别处改过）
  await auth.fetchMe().catch(() => {})
  // 取/建会话 + 拉历史 + 建立 WS 长连接（内部幂等，重复进入不重复初始化）
  chat.ensureReady()
})

function onCommand(cmd: string) {
  if (cmd === 'profile') {
    profileVisible.value = true
  } else if (cmd === 'logout') {
    ElMessageBox.confirm('确定要退出登录吗？', '提示', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning',
    })
      .then(() => {
        chat.reset() // 断开 WS + 清空本地会话状态，避免下个账号串数据
        auth.logout()
        router.push({ name: 'Login' })
      })
      .catch(() => {})
  }
}
</script>

<template>
  <div class="home-page starfield">
    <!-- 顶部玻璃导航 -->
    <header class="nav-bar">
      <div class="nav-inner">
        <div class="brand">
          <svg class="brand-mark" viewBox="0 0 40 40" aria-hidden="true">
            <rect width="40" height="40" rx="11" fill="rgba(242,176,76,.12)" />
            <path
              d="M24 8.5a13 13 0 1 0 4 17 10.5 10.5 0 0 1-4-17z"
              fill="#F2B04C"
            />
            <circle cx="30" cy="9" r="1.6" fill="#B9A5E0" />
          </svg>
          <div class="brand-text">
            <span class="brand-cn">日奈宇宙</span>
            <span class="brand-en">HINAVERSE</span>
          </div>
        </div>

        <div class="nav-actions">
          <!-- 星历入口：日记 / 打卡 -->
          <router-link class="nav-link" :to="{ name: 'Diary' }">
            <el-icon><Tickets /></el-icon>日记
          </router-link>
          <router-link class="nav-link" :to="{ name: 'Checkin' }">
            <el-icon><Calendar /></el-icon>打卡
          </router-link>
        </div>

        <el-dropdown trigger="click" @command="onCommand">
          <div class="user-area">
            <div class="user-avatar">
              <img v-if="auth.profile.avatar" :src="auth.profile.avatar" class="avatar-img" />
              <span v-else class="avatar-letter">{{
                auth.profile.nickname ? auth.profile.nickname.charAt(0).toUpperCase() : 'U'
              }}</span>
            </div>
            <span class="user-name">{{ auth.profile.nickname }}</span>
            <el-icon class="caret"><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">
                <el-icon><User /></el-icon>个人资料
              </el-dropdown-item>
              <el-dropdown-item divided command="logout">
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <!-- 主星空 · 对话 -->
    <main class="main">
      <ChatWindow />
    </main>

    <ProfileDialog v-model="profileVisible" />
  </div>
</template>

<style scoped>
.home-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
}

/* 玻璃导航栏 */
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

.brand-text {
  display: flex;
  align-items: baseline;
  gap: 10px;
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

.user-area {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 999px;
  transition: background 0.2s;
}
.user-area:hover {
  background: var(--nv-amber-soft);
}

.user-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--nv-amber), var(--nv-amber-deep));
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  flex-shrink: 0;
  box-shadow: 0 0 10px rgba(242, 176, 76, 0.3);
}
.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.avatar-letter {
  color: var(--nv-amber-ink);
  font-weight: 700;
  font-size: 15px;
}

.user-name {
  font-size: 14px;
  color: var(--nv-text);
}

/* 星历入口 */
.nav-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 999px;
  font-size: 13px;
  color: var(--nv-text-soft);
  text-decoration: none;
  transition: background 0.2s, color 0.2s;
}
.nav-link:hover {
  background: var(--nv-amber-soft);
  color: var(--nv-amber);
}

.caret {
  color: var(--nv-text-muted);
  font-size: 12px;
}

/* 主体 */
.main {
  flex: 1;
  display: flex;
  justify-content: center;
  padding: 24px 24px 28px;
  position: relative;
  z-index: 1;
}
</style>