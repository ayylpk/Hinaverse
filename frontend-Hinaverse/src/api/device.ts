/**
 * 极光推送设备绑定（只在安卓壳里生效，浏览器里整个逻辑自动跳过）。
 *
 * 背景：远程模式壳的 WebView 里，Capacitor 会把原生插件注入到
 * window.Capacitor.Plugins.JPush（插件装在 app-Hinaverse 壳工程，前端零依赖）。
 * 所以这里不 import 任何 capacitor 包，直接摸 window 上的对象——
 * 浏览器里 Capacitor 不存在 → 返回 null → 本文件等于不存在。
 *
 * 链路：申请通知权限 → startJPush 注册 → 轮询拿 registrationID（SDK 注册有延迟）
 *      → POST /api/device/reg_id（带 JWT）→ 后端写 User.reg_id → 离线推送按此发极光。
 */
import type { Router } from 'vue-router'
import { http } from '@/api/http'

/** 只声明我们用到的三个方法（对齐 capacitor-plugin-jpush@4 的 JS API） */
interface JPushBridge {
  requestPermissions(): Promise<{ permission: string }>
  startJPush(): Promise<void>
  getRegistrationID(): Promise<{ registrationId: string }>
}

/** 取壳里注入的 JPush 插件；浏览器环境返回 null */
function jpushBridge(): JPushBridge | null {
  const cap = (window as { Capacitor?: { Plugins?: Record<string, unknown> } }).Capacitor
  const plugin = cap?.Plugins?.JPush
  return (plugin as JPushBridge) ?? null
}

// ────────────────── 安卓返回键接管（仅壳内生效） ──────────────────
// 约定协议：壳的 MainActivity 拦到返回键后 evaluateJavascript 问 window.__hinaBack——
// 返回 true = 页面消化了（回首页/弹提示），false = 壳放行退出。
// 旧版线上站点没有 __hinaBack，壳拿 'false' 走默认行为，前后端部署顺序无依赖。

/** 自带小 toast：不 import ElMessage（避开按需样式注入在 ts 文件里失效的老坑） */
function shellToast(text: string) {
  const el = document.createElement('div')
  el.textContent = text
  el.style.cssText =
    'position:fixed;left:50%;bottom:calc(88px + env(safe-area-inset-bottom));transform:translateX(-50%);' +
    'background:rgba(20,27,46,.92);color:#F3EFE6;padding:10px 18px;border-radius:999px;font-size:13px;' +
    'border:1px solid rgba(242,176,76,.25);z-index:9999;transition:opacity .3s;pointer-events:none'
  document.body.appendChild(el)
  setTimeout(() => {
    el.style.opacity = '0'
    setTimeout(() => el.remove(), 350)
  }, 1600)
}

/**
 * 壳内注册返回键处理：非聊天页 → 先回聊天；聊天页双击（2s 内两按）才真退出。
 * 浏览器/桌面环境没有 window.Capacitor，整段不执行，零影响。
 */
export function setupShellBackHandler(router: Router): void {
  if (!(window as { Capacitor?: unknown }).Capacitor) return
  let lastBackAt = 0
  ;(window as { __hinaBack?: () => boolean }).__hinaBack = () => {
    const path = router.currentRoute.value.path
    if (path !== '/home' && path !== '/') {
      router.push('/home')
      return true
    }
    const now = Date.now()
    if (now - lastBackAt < 2000) return false // 第二次按 → 放行退出
    lastBackAt = now
    shellToast('再按一次退出日奈宇宙')
    return true
  }
}

/** 防重入：applyAuth 和冷启动两条路都调，只真正执行一次 */
let binding = false

/** 绑定当前设备到极光并上报 reg_id。任何失败只打日志——推是锦上添花，不能影响聊天主流程 */
export async function bindDeviceForPush(): Promise<void> {
  const jp = jpushBridge()
  if (!jp || binding) return
  binding = true
  try {
    // Android 13+ 通知权限是运行时申请；拒绝也不中断（拿 reg_id 照样上报，只是不弹通知）
    try {
      await jp.requestPermissions()
    } catch {
      /* 权限弹窗失败继续走 */
    }
    await jp.startJPush()
    // registrationID 要等极光服务器注册完才有值，最长轮询 ~9 秒
    let rid = ''
    for (let i = 0; i < 6 && !rid; i++) {
      await new Promise((r) => setTimeout(r, 1500))
      rid = (await jp.getRegistrationID()).registrationId || ''
    }
    if (!rid) {
      console.warn('[device] 拿不到极光 registrationId（网络/包名不匹配？），跳过上报')
      return
    }
    await http.post<{ ok: boolean }>('/api/device/reg_id', { reg_id: rid })
    console.log('[device] 极光 reg_id 上报成功')
  } catch (e) {
    console.warn('[device] 极光绑定失败（不影响聊天）', e)
  }
}
