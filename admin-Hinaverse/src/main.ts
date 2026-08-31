import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

// ⚠️ 挂 html.dark：Element Plus 的组件级 CSS 按需加载、顺序在我们 style.css 之后，
// 其 :root 令牌会把我们的暗色覆盖盖回白（详情抽屉白底浅字看不清即此故）。
// style.css 令牌块已写成 `:root, html.dark`——html.dark 权重更高，恒压过 EP。
document.documentElement.classList.add('dark')

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
