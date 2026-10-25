import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  reporter: [["list"]],
  timeout: 120000,
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: "http://127.0.0.1:4173",
    // 本机没有下载 chromium 时用系统 Edge（QUESTOR_BROWSER_CHANNEL=msedge）；CI 用默认 chromium。
    ...(process.env.QUESTOR_BROWSER_CHANNEL
      ? { channel: process.env.QUESTOR_BROWSER_CHANNEL as "msedge" | "chrome" }
      : {}),
    headless: true,
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
