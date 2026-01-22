import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  root: 'client',
  publicDir: 'public',
  server: {
    host: true,
  },
  build: {
    outDir: '../dist',
  },
})
