import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { SERVER_URL } from './config.ts';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: true,
    proxy: {
      '/api': {
        target: SERVER_URL,
        changeOrigin: true,
      }
    }
  },
})
