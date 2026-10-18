import { defineConfig } from "vite";

// 桌面薄客户端：Vite 构建产物输出到 dist/，由 sidecar（--serve，QUESTOR_WEB_DIST）一并伺服。
// base './' 让产物可被任意 loopback 路径下加载（不假设站点根路径）。
export default defineConfig({
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
