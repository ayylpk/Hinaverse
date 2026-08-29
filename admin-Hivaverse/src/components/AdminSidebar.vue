<script setup lang="ts">
/** 运营台左侧边栏：logo + 菜单（危机事件 / 人工接管）+ 当前运营者 + 退出 */
import { useRouter } from 'vue-router'
import { Headset, User, Warning } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

defineProps<{ active: 'crisis' | 'takeover' }>()

const router = useRouter()
const auth = useAuthStore()

function onLogout() {
  auth.logout()
  router.push({ name: 'Login' })
}
</script>

<template>
  <aside class="sidebar">
    <div class="logo">
      <svg class="logo-mark" viewBox="0 0 40 40" aria-hidden="true">
        <rect width="40" height="40" rx="11" fill="rgba(242,176,76,.12)" />
        <path d="M24 8.5a13 13 0 1 0 4 17 10.5 10.5 0 0 1-4-17z" fill="#F2B04C" />
        <circle cx="30" cy="9" r="1.6" fill="#B9A5E0" />
      </svg>
      <div class="logo-text">
        <div class="logo-cn">日奈宇宙</div>
        <div class="logo-en">运营台</div>
      </div>
    </div>

    <nav class="menu">
      <router-link class="menu-item" :class="{ active: active === 'crisis' }" :to="{ name: 'Crisis' }">
        <el-icon><Warning /></el-icon>
        <span>危机事件</span>
      </router-link>
      <router-link class="menu-item" :class="{ active: active === 'takeover' }" :to="{ name: 'Takeover' }">
        <el-icon><Headset /></el-icon>
        <span>人工接管</span>
      </router-link>
    </nav>

    <div class="sidebar-foot">
      <div class="operator">
        <el-icon><User /></el-icon>
        <span class="operator-name">{{ auth.user?.nickname || auth.user?.username }}</span>
      </div>
      <el-button size="small" text @click="onLogout">退出登录</el-button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  flex: 0 0 210px;
  display: flex;
  flex-direction: column;
  padding: 22px 14px 18px;
  background: var(--nv-surface);
  backdrop-filter: blur(14px);
  border-right: 1px solid var(--nv-border);
  position: sticky;
  top: 0;
  height: 100vh;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 8px 20px;
  border-bottom: 1px solid var(--nv-border);
}
.logo-mark {
  width: 38px;
  height: 38px;
  filter: drop-shadow(0 0 10px rgba(242, 176, 76, 0.35));
}
.logo-cn {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 3px;
  color: var(--nv-text);
  line-height: 1.2;
}
.logo-en {
  font-size: 10px;
  letter-spacing: 4px;
  color: var(--nv-text-muted);
  margin-top: 1px;
}

.menu {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-radius: var(--radius-sm);
  color: var(--nv-text-soft);
  font-size: 14px;
  text-decoration: none;
  transition: background 0.2s, color 0.2s;
}
.menu-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--nv-text);
}
.menu-item.active {
  background: var(--nv-amber-soft);
  color: var(--nv-amber);
  font-weight: 600;
}

.sidebar-foot {
  margin-top: auto;
  border-top: 1px solid var(--nv-border);
  padding-top: 14px;
}
.operator {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--nv-text-soft);
  font-size: 13px;
  margin-bottom: 6px;
}
.operator-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 110px;
}
</style>
