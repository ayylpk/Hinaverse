import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
    }),
    Components({
      resolvers: [ElementPlusResolver()],
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  // 依赖优化缓存放系统临时目录：本机 WorkBuddy 的 safe-delete 会拦截
  // node_modules/.vite 下的目录清理导致 vite 启动即崩，挪到临时目录走原生删除
  cacheDir: join(tmpdir(), 'hinaverse-front-vite-cache'),
  // 开发代理：前端跑 517x，后端 FastAPI 跑 8000
  // 页面里写 /api/xxx、/ws 即可，Vite 负责转发（这也避开了后端 CORS 配置差异）
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true, // WebSocket 升级握手也要代理
      },
    },
  },
  // vite preview 同样要代理（本地起 dist 做移动端视口截图验收时用）
  preview: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
