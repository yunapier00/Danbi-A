/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 빌드 결과는 FastAPI가 그대로 내보낸다 (danbi/api/web → "/", "/dev", "/assets/*").
// 개발 중에는 `npm run dev`(5173)가 /api 요청을 FastAPI(8000)로 넘긴다.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../danbi/api/web", emptyOutDir: true },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "jsdom" },
});
