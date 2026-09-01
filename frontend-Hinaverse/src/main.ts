import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { setupShellBackHandler } from './api/device'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
// 安卓壳返回键接管（浏览器环境内部直接 return）
setupShellBackHandler(router)
app.mount('#app')
