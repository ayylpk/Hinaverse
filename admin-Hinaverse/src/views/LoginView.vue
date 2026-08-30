<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/http'

const router = useRouter()
const auth = useAuthStore()

const form = ref({ username: '', password: '' })
const loading = ref(false)

async function onSubmit() {
  if (loading.value) return
  if (form.value.username.trim().length < 3) {
    ElMessage.error('账号至少需要 3 个字符')
    return
  }
  if (form.value.password.length < 6) {
    ElMessage.error('密码至少需要 6 位')
    return
  }

  try {
    loading.value = true
    // 普通用户登录流程，登录后拿到的 user 里带 role
    await auth.login(form.value.username.trim(), form.value.password)
    // 非管理员：提示无权限并登出（后端危机接口也会 403 兜底）
    if (!auth.isAdmin) {
      auth.logout()
      ElMessage.error('无运营权限，已退出登录')
      return
    }
    ElMessage.success('欢迎回来，运营者')
    router.push({ name: 'Crisis' })
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? e.detail : '网络开小差了，请稍后再试')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page starfield">
    <div class="moon-glow"></div>

    <div class="login-card">
      <div class="brand">
        <svg class="brand-mark" viewBox="0 0 40 40" aria-hidden="true">
          <rect width="40" height="40" rx="11" fill="rgba(242,176,76,.12)" />
          <path d="M24 8.5a13 13 0 1 0 4 17 10.5 10.5 0 0 1-4-17z" fill="#F2B04C" />
          <circle cx="30" cy="9" r="1.6" fill="#B9A5E0" />
        </svg>
        <div class="brand-text">
          <div class="brand-cn">日奈宇宙</div>
          <div class="brand-en">运营台 · ADMIN</div>
        </div>
      </div>

      <h1 class="title">运营者登录</h1>
      <p class="subtitle">危机干预与人工介入入口，仅限管理员账号</p>

      <el-form @submit.prevent="onSubmit" class="form">
        <el-form-item>
          <el-input v-model="form.username" placeholder="账号" size="large" clearable>
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            size="large"
            show-password
            @keyup.enter="onSubmit"
          >
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>

        <el-button type="primary" size="large" class="login-btn" :loading="loading" @click="onSubmit">
          进入运营台 <span class="arrow">→</span>
        </el-button>
      </el-form>

      <p class="footer-line">
        <span class="twinkle">✦</span>
        普通用户账号无法登录此后台
      </p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  position: relative;
  overflow: hidden;
}

.moon-glow {
  position: absolute;
  top: -140px;
  right: -100px;
  width: 560px;
  height: 560px;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    rgba(242, 176, 76, 0.18) 0%,
    rgba(242, 176, 76, 0.06) 40%,
    transparent 70%
  );
  pointer-events: none;
}

.login-card {
  width: 100%;
  max-width: 420px;
  background: var(--nv-surface);
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  padding: 44px 40px 36px;
  position: relative;
  z-index: 1;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}
.brand-mark {
  width: 40px;
  height: 40px;
  filter: drop-shadow(0 0 12px rgba(242, 176, 76, 0.35));
}
.brand-cn {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 4px;
  color: var(--nv-text);
  line-height: 1.2;
}
.brand-en {
  font-size: 10px;
  letter-spacing: 4px;
  color: var(--nv-text-muted);
  margin-top: 1px;
}

.title {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 600;
  margin: 0 0 6px;
  color: var(--nv-text);
  letter-spacing: 2px;
}
.subtitle {
  font-size: 13px;
  color: var(--nv-text-soft);
  margin: 0 0 30px;
}

.form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.login-btn {
  width: 100%;
  height: 48px;
  border-radius: var(--radius-md);
  font-size: 16px;
  letter-spacing: 3px;
}
.login-btn .arrow {
  margin-left: 6px;
  transition: transform 0.2s;
}
.login-btn:hover .arrow {
  transform: translateX(4px);
}

.footer-line {
  text-align: center;
  font-size: 12px;
  color: var(--nv-text-muted);
  margin: 30px 0 0;
  letter-spacing: 1px;
}
.footer-line .twinkle {
  color: var(--nv-amber);
  margin-right: 6px;
}
</style>
