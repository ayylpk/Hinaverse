<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
// ⚠️ 图标库不走自动注册，用到就得显式 import（同 HomeView 的规矩）
import { Cellphone } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/http'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [val: boolean] }>()

const auth = useAuthStore()

/** 弹窗宽度：窄屏（含手机壳）给 92%，桌面维持 460px 原设计 */
const dialogWidth = window.innerWidth <= 640 ? '92%' : '460px'

const nickname = ref(auth.profile.nickname)
const avatar = ref(auth.profile.avatar)
const currentPwd = ref('')
const newPwd = ref('')
const confirmPwd = ref('')
const saving = ref(false)

watch(
  () => props.modelValue,
  (val) => {
    if (val) {
      nickname.value = auth.profile.nickname
      avatar.value = auth.profile.avatar
      currentPwd.value = ''
      newPwd.value = ''
      confirmPwd.value = ''
    }
  }
)

function close() {
  emit('update:modelValue', false)
}

function onAvatarChange(file: File) {
  const reader = new FileReader()
  reader.onload = () => {
    avatar.value = String(reader.result)
  }
  reader.readAsDataURL(file)
  return false // 阻止自动上传
}

async function onSave() {
  if (saving.value) return

  // 若填写了密码相关字段，则做前端格式校验（当前密码是否正确交给后端判）
  const hasPwdInput = currentPwd.value || newPwd.value || confirmPwd.value
  if (hasPwdInput) {
    if (!newPwd.value || newPwd.value.length < 6) {
      ElMessage.error('新密码至少 6 位')
      return
    }
    if (newPwd.value !== confirmPwd.value) {
      ElMessage.error('两次输入的新密码不一致')
      return
    }
  }

  if (!nickname.value.trim()) {
    ElMessage.error('昵称不能为空')
    return
  }

  saving.value = true
  try {
    await auth.updateProfile({
      nickname: nickname.value.trim(),
      avatar: avatar.value,
      // 填了密码才带这两个字段，后端验 current_password；没填就只改资料
      ...(hasPwdInput
        ? { current_password: currentPwd.value, new_password: newPwd.value }
        : {}),
    })
    ElMessage.success('保存成功')
    close()
  } catch (e) {
    // 当前密码错、昵称过长等后端 detail 直接展示
    ElMessage.error(e instanceof ApiError ? e.detail : '保存失败，请稍后再试')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="个人资料"
    :width="dialogWidth"
    :close-on-click-modal="false"
    @close="close"
  >
    <div class="profile-form">
      <!-- 头像 -->
      <div class="avatar-row">
        <div class="avatar-wrap">
          <img v-if="avatar" :src="avatar" class="avatar-img" alt="avatar" />
          <div v-else class="avatar-placeholder">
            {{ nickname ? nickname.charAt(0).toUpperCase() : 'U' }}
          </div>
          <el-upload
            class="avatar-uploader"
            :show-file-list="false"
            :before-upload="onAvatarChange"
            accept="image/*"
          >
            <div class="upload-mask">更换</div>
          </el-upload>
        </div>
        <p class="avatar-tip">点击头像可更换图片</p>
      </div>

      <el-form label-position="top" class="form">
        <el-form-item label="昵称">
          <el-input v-model="nickname" placeholder="请输入昵称" maxlength="20" show-word-limit />
        </el-form-item>

        <el-divider content-position="left">修改密码</el-divider>

        <el-form-item label="当前密码">
          <el-input v-model="currentPwd" type="password" placeholder="请输入当前密码" show-password />
        </el-form-item>

        <el-form-item label="新密码">
          <el-input v-model="newPwd" type="password" placeholder="至少 6 位" show-password />
        </el-form-item>

        <el-form-item label="确认新密码">
          <el-input v-model="confirmPwd" type="password" placeholder="再次输入新密码" show-password />
        </el-form-item>
      </el-form>

      <!-- 安卓客户端下载入口（与顶栏下拉「下载 App」同源链接；/apk/hina.apk 由 nginx 静态直出，发版覆盖文件即可） -->
      <el-divider content-position="left">日奈宇宙 App</el-divider>
      <div class="apk-row">
        <p class="apk-tip">下载安卓客户端，用同一账号登录，让日奈更容易找到你。</p>
        <a class="apk-btn" href="/apk/hina.apk" download target="_blank">
          <el-icon><Cellphone /></el-icon>下载安卓安装包
        </a>
      </div>
    </div>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存修改</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.profile-form {
  padding: 8px 4px 0;
}

.avatar-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 8px;
}

.avatar-wrap {
  position: relative;
  width: 88px;
  height: 88px;
  border-radius: 50%;
  overflow: hidden;
  cursor: pointer;
  border: 2px solid var(--nv-border-strong);
  transition: border-color 0.2s, box-shadow 0.2s;
}
.avatar-wrap:hover {
  border-color: var(--nv-amber);
  box-shadow: 0 0 16px rgba(242, 176, 76, 0.35);
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--nv-amber), var(--nv-amber-deep));
  color: var(--nv-amber-ink);
  font-size: 34px;
  font-weight: 700;
}

.avatar-uploader {
  position: absolute;
  inset: 0;
}

.upload-mask {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  font-size: 13px;
  opacity: 0;
  transition: opacity 0.2s;
}
.avatar-wrap:hover .upload-mask {
  opacity: 1;
}

.avatar-tip {
  font-size: 12px;
  color: var(--nv-text-muted);
  margin: 10px 0 0;
}

.form {
  margin-top: 12px;
}

/* ---- App 下载区 ---- */
.apk-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 4px 0 8px;
}

.apk-tip {
  margin: 0;
  font-size: 12px;
  color: var(--nv-text-muted);
  text-align: center;
  line-height: 1.7;
}

/* 锚点伪装主按钮：琥珀渐变胶囊，与头像描边/品牌色一致 */
.apk-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 24px;
  border-radius: 999px;
  background: linear-gradient(135deg, var(--nv-amber), var(--nv-amber-deep));
  color: var(--nv-amber-ink);
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  transition: box-shadow 0.2s, transform 0.2s;
}
.apk-btn:hover {
  box-shadow: 0 0 16px rgba(242, 176, 76, 0.35);
  transform: translateY(-1px);
}
</style>
