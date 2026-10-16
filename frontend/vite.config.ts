import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

/**
 * 开发服务器把后端路径整段代理给 Django，浏览器只见一个源，
 * 会话 Cookie 与 CSRF 都按同域处理；生产构建产物由 Nginx 同域托管，不存在跨域。
 *
 * 后端地址从环境变量 VITE_API_TARGET 读，默认 http://127.0.0.1:8000。
 */
const PROXY_PATHS = ['/api', '/_allauth', '/media', '/admin', '/static']

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: true, // 允许同网段手机直接访问，方便真机验移动端布局
      port: 5173,
      proxy: Object.fromEntries(
        PROXY_PATHS.map((path) => [
          path,
          {
            target,
            changeOrigin: true, // Host 改写成后端，配合后端 ALLOWED_HOSTS
            secure: false,
          },
        ]),
      ),
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
    },
  }
})
