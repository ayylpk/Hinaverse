<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import hinaMoon from '@/assets/img/hina-moon.png'

const router = useRouter()
const auth = useAuthStore()

const form = ref({
  username: '',
  password: '',
})
const loading = ref(false)

/** 图片加载失败时兜底：换成 CSS 月亮（图没生成好也能看） */
const imgOk = ref(true)

async function onLogin() {
  if (loading.value) return
  loading.value = true
  await new Promise((r) => setTimeout(r, 400)) // 模拟网络延迟
  const ok = auth.login(form.value.username, form.value.password)
  loading.value = false
  if (ok) {
    ElMessage.success('欢迎回来，日奈已经在等你了')
    router.push({ name: 'Home' })
  } else {
    ElMessage.error('账号或密码不正确')
  }
}
</script>

<template>
  <div class="login-page starfield">
    <!-- 远空的月光晕 -->
    <div class="moon-glow"></div>

    <div class="login-shell">
      <!-- 左：月下独白（品牌 + 角色 + 一句夜话） -->
      <section class="showcase">
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
            <div class="brand-cn">日奈宇宙</div>
            <div class="brand-en">HINAVERSE</div>
          </div>
        </div>

        <div class="hero">
          <!-- 呼吸光晕 + 轨道环：这页的签名元素 -->
          <div class="halo"></div>
          <div class="orbit">
            <span class="orbit-star"></span>
          </div>
          <img
            v-if="imgOk"
            :src="hinaMoon"
            alt="日奈在夜空下"
            class="hero-img"
            @error="imgOk = false"
          />
          <!-- 图片兜底：CSS 月亮 -->
          <div v-else class="css-moon">
            <div class="css-moon-face">
              <div class="css-eye left"></div>
              <div class="css-eye right"></div>
              <div class="css-blush lb"></div>
              <div class="css-blush rb"></div>
              <div class="css-mouth"></div>
            </div>
            <div class="css-hair"></div>
          </div>
        </div>

        <h1 class="headline">在深夜里，有人为你亮着灯</h1>
        <p class="sub">
          你就是夜航的坐标。你说出的话，都会变成夜空里的星。
        </p>
      </section>

      <!-- 右：登录卡（宇宙站的舷窗） -->
      <section class="card-col">
        <div class="login-card">
          <h2 class="title">进入宇宙站</h2>
          <p class="subtitle">欢迎回来，今天也辛苦了</p>

          <el-form @submit.prevent="onLogin" class="form">
            <el-form-item>
              <el-input
                v-model="form.username"
                placeholder="账号"
                size="large"
                clearable
              >
                <template #prefix>
                  <el-icon><User /></el-icon>
                </template>
              </el-input>
            </el-form-item>

            <el-form-item>
              <el-input
                v-model="form.password"
                type="password"
                placeholder="密码"
                size="large"
                show-password
                @keyup.enter="onLogin"
              >
                <template #prefix>
                  <el-icon><Lock /></el-icon>
                </template>
              </el-input>
            </el-form-item>

            <el-button
              type="primary"
              size="large"
              class="login-btn"
              :loading="loading"
              @click="onLogin"
            >
              进入夜晚 <span class="arrow">→</span>
            </el-button>
          </el-form>

          <p class="footer-line">
            <span class="twinkle">✦</span> 你说出的每句话，都会点亮一颗星
          </p>
        </div>
      </section>
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
  padding: 48px 32px;
  position: relative;
  overflow: hidden;
}

/* 远空月光晕 —— 画面唯一的环境光 */
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
  animation: breathe 7s ease-in-out infinite;
}

.login-shell {
  width: 100%;
  max-width: 1180px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 72px;
  position: relative;
  z-index: 1;
}

/* ---------- 左侧展示 ---------- */
.showcase {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  width: 42px;
  height: 42px;
  filter: drop-shadow(0 0 12px rgba(242, 176, 76, 0.35));
}

.brand-cn {
  font-family: var(--font-display);
  font-size: 21px;
  font-weight: 600;
  letter-spacing: 4px;
  color: var(--nv-text);
  line-height: 1.2;
}
.brand-en {
  font-size: 10px;
  letter-spacing: 5px;
  color: var(--nv-text-muted);
  margin-top: 1px;
}

/* 角色插画区 */
.hero {
  position: relative;
  width: 300px;
  height: 300px;
  margin: 20px auto 8px;
}
.hero-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 50%;
  position: relative;
  z-index: 2;
  border: 1px solid var(--nv-border-strong);
  box-shadow: var(--shadow-lg);
  animation: hero-in 1s ease-out both;
}
@keyframes hero-in {
  from {
    opacity: 0;
    transform: translateY(24px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* 呼吸光晕（月亮体温） */
.halo {
  position: absolute;
  inset: -34px;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    rgba(242, 176, 76, 0.34) 0%,
    rgba(242, 176, 76, 0.12) 45%,
    rgba(185, 165, 224, 0.08) 70%,
    transparent 100%
  );
  filter: blur(6px);
  animation: breathe 4.5s ease-in-out infinite;
  z-index: 1;
}

/* 轨道环：一颗小星沿着环慢慢绕月运行 */
.orbit {
  position: absolute;
  inset: 10px;
  border: 1px dashed rgba(185, 165, 224, 0.45);
  border-radius: 50%;
  animation: orbit 36s linear infinite;
  z-index: 3;
  pointer-events: none;
}
.orbit-star {
  position: absolute;
  top: 8px;
  left: 50%;
  width: 8px;
  height: 8px;
  margin-left: -4px;
  border-radius: 50%;
  background: var(--nv-amber);
  box-shadow:
    0 0 10px var(--nv-amber),
    0 0 22px rgba(242, 176, 76, 0.6);
}

/* 标题文案 */
.headline {
  font-family: var(--font-display);
  font-size: 34px;
  font-weight: 600;
  color: var(--nv-text);
  margin: 18px 0 10px;
  line-height: 1.4;
  letter-spacing: 1px;
}
.sub {
  font-size: 14px;
  color: var(--nv-text-soft);
  margin: 0;
  letter-spacing: 0.5px;
}

/* ---------- 右侧登录卡 ---------- */
.card-col {
  flex: 0 0 400px;
}

.login-card {
  background: var(--nv-surface);
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
  border: 1px solid var(--nv-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  padding: 44px 40px 36px;
}

.title {
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 600;
  margin: 0 0 6px;
  color: var(--nv-text);
  letter-spacing: 2px;
}

.subtitle {
  font-size: 14px;
  color: var(--nv-text-soft);
  margin: 0 0 32px;
}

.form {
  margin-top: 8px;
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
  margin: 32px 0 0;
  letter-spacing: 1px;
}
.footer-line .twinkle {
  color: var(--nv-amber);
  margin-right: 6px;
}

/* ---------------- 图片兜底：CSS 月亮 ---------------- */
.css-moon {
  position: relative;
  z-index: 2;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  overflow: hidden;
  background: linear-gradient(180deg, #1b2240 0%, #141b2e 100%);
  border: 1px solid var(--nv-border-strong);
  display: flex;
  align-items: center;
  justify-content: center;
}
.css-moon-face {
  position: relative;
  width: 110px;
  height: 118px;
  background: #f6ede2;
  border-radius: 50% 50% 44% 44%;
  z-index: 2;
}
.css-eye {
  position: absolute;
  top: 46px;
  width: 11px;
  height: 15px;
  background: #5a4f4a;
  border-radius: 50%;
}
.css-eye.left {
  left: 28px;
}
.css-eye.right {
  right: 28px;
}
.css-blush {
  position: absolute;
  top: 66px;
  width: 17px;
  height: 8px;
  background: rgba(242, 176, 76, 0.5);
  border-radius: 50%;
}
.css-blush.lb {
  left: 15px;
}
.css-blush.rb {
  right: 15px;
}
.css-mouth {
  position: absolute;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 10px;
  border-bottom: 2.5px solid #c9a0a0;
  border-radius: 0 0 18px 18px;
}
/* 兜底用的头发（琥珀月色发丝） */
.css-moon::before {
  content: '';
  position: absolute;
  top: -6%;
  left: 50%;
  transform: translateX(-50%);
  width: 170px;
  height: 170px;
  background: linear-gradient(180deg, #f4c07a 0%, #dd9648 75%);
  border-radius: 50% 50% 40% 40%;
  z-index: 1;
}

/* ---------------- 响应式 ---------------- */
@media (max-width: 980px) {
  .login-shell {
    flex-direction: column;
    gap: 40px;
    max-width: 440px;
  }
  .showcase {
    align-items: center;
    text-align: center;
  }
  .hero {
    width: 220px;
    height: 220px;
    margin: 16px auto 4px;
  }
  .headline {
    font-size: 26px;
  }
  .card-col {
    flex: 1;
    width: 100%;
  }
  .login-card {
    padding: 36px 28px 32px;
  }
}
</style>