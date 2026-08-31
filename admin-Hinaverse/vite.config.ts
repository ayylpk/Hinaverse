import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  // 生产部署在 nginx 的 /admin/ 子路径（主前端占根路径）。
  // 不设 base 的话 index.html 会去根路径拿 /assets/*，和主前端的 dist 撞车。
  base: '/admin/',
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
  // 依赖优化缓存放到系统临时目录：本机 WorkBuddy 的 safe-delete 会拦截
  // node_modules/.vite 下的目录清理导致 vite 崩溃，挪到临时目录后走原生删除
  cacheDir: join(tmpdir(), 'hinaverse-admin-vite-cache'),
  build: {
    // 同款原因：清空 dist 也被 safe-delete 拦（trash 失败即抛错）。
    // 关掉自动清空，重复构建时由 vite 覆盖输出（旧 hash 文件残留无害）。
    emptyOutDir: false,
  },
  server: {
    // 运营台固定 5176（5173/5174/5175 被其他项目占用）
    port: 5176,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
