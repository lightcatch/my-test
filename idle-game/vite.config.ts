import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: '边境日志 - 勇士放置游戏',
        short_name: '边境日志',
        description: '文字优先的勇士放置冒险',
        theme_color: '#121922',
        background_color: '#121922',
        display: 'standalone',
        icons: []
      }
    })
  ]
});
