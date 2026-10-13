import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vite';

// 开发模式的只读本机证据 API 始终通过同源 Vite 代理；避免跨域读取本机文件。
// 正式部署保留现有 VITE_PLATFORM_API_URL 配置，只有本机启动器才使用私有代理覆盖。
const platformApiTarget = process.env.STORYOS_PLATFORM_PROXY_TARGET || process.env.VITE_PLATFORM_API_URL || 'http://127.0.0.1:8080';

const platformProxy = {
  '/api/v1/draft-vault': { target: process.env.STORYOS_R17_TEST_PROXY_TARGET || 'http://127.0.0.1:19118', changeOrigin: true },
  '/api': {
    target: platformApiTarget,
    changeOrigin: true,
  },
  '/healthz': {
    target: platformApiTarget,
    changeOrigin: true,
  },
};

export default defineConfig(() => {
  return {
    // Portable build assets must load both from the hosted console and the
    // isolated file:// browser QA used by offline production evidence tests.
    base: './',
    plugins: [react(), tailwindcss()],
    build: {
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            // 历史 Run 大包只随监控模块加载；Episode 证据与 Registry 分别独立。
            const normalized = id.replace(/\\/g, '/');

          },
        },
      },
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // Optional local-agent optimization: disable HMR/file watching when
      // DISABLE_HMR=true to reduce file-system churn during automated edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
      proxy: platformProxy,
    },
    preview: { proxy: platformProxy },
  };
});
