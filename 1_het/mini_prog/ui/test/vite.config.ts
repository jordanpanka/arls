import { defineConfig } from 'vitest/config'
import preact from '@preact/preset-vite'


export default defineConfig({
  plugins: [preact()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:5293",
        changeOrigin: true
      }
    }
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts"
    }
});

