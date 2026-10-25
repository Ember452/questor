/** Electron 真壳冒烟：启动 → 握手 → cookie → 加载 apps/web/dist → 看到导航。 */
import { existsSync } from "node:fs";
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { _electron as electron } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../../..");

const engine = process.env.QUESTOR_ENGINE ?? resolve(REPO, "apps/desktop/dist/engine/questor-engine.exe");
const electronExe = resolve(REPO, "apps/desktop/node_modules/electron/dist/electron.exe");
const webDist = resolve(REPO, "apps/web/dist");
const screenshot = resolve(REPO, "apps/web/e2e/__screenshots__/electron-shell.png");

/** 产物预检：缺什么直接说清楚，不留给 Playwright 一个"failed to launch"。 */
function preflight() {
  const missing = [
    ["engine exe", engine],
    ["electron exe", electronExe],
    ["web dist", webDist],
  ].filter(([, target]) => !existsSync(target));
  if (missing.length > 0) {
    console.error("e2e-electron preflight failed — missing artifacts:");
    for (const [name, target] of missing) console.error(`  ${name}: ${target}`);
    console.error("hint: 先跑 node scripts/build-engine.mjs 与 npm --prefix ../web run build:web");
    process.exit(1);
  }
}

async function main() {
  preflight();
  console.log("engine:", engine);
  console.log("electron:", electronExe);

  const app = await electron.launch({
    executablePath: electronExe,
    // CI Windows runner 无 GPU/交互桌面：禁用 GPU/沙箱，参数必须在 app 路径之前。
    args: ["--disable-gpu", "--no-sandbox", resolve(REPO, "apps/desktop")],
    env: {
      ...process.env,
      ELECTRON_DISABLE_GPU: "1",
      QUESTOR_ENGINE: engine,
      QUESTOR_WEB_DIST: webDist,
    },
  });

  try {
    const page = await app.firstWindow();
    await page.waitForURL(/127\.0\.0\.1:\d+\//, { timeout: 60000 });
    await page.waitForTimeout(2000);
    console.log("url:", page.url());
    console.log("body:", (await page.locator("body").innerText()).slice(0, 400));
    await page.screenshot({ path: screenshot, fullPage: true });
    await page.getByText("Questor").waitFor({ timeout: 30000 });
    await page.getByRole("navigation").waitFor({ timeout: 30000 });
    writeFileSync(resolve(REPO, "apps/web/.e2e-electron-url.txt"), page.url(), "utf8");
    console.log("electron url:", page.url());
  } finally {
    await app.close();
  }
}

main().catch((error) => {
  console.error("e2e-electron failed:", error);
  console.error("hint: 引擎/主进程的输出带 [engine]/[boot] 前缀打印在 stderr；窗口先于引擎创建，firstWindow 不应超时。");
  process.exit(1);
});
