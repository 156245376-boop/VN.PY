import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 前端 dev server 通过代理把 /api 与 /ws 转发到后端 8000 端口,
// 避免跨域并简化前端请求地址。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": { target: "http://localhost:8180", changeOrigin: true },
      "/ws": { target: "ws://localhost:8180", ws: true },
    },
  },
});
