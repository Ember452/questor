/** Electron 真壳冒烟：启动 → 握手 → cookie → 加载 apps/web/dist → 看到导航。 */
import { _electron as electron } from "playwright";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = resolve(WEB, "../..");
const engine = resolve(REPO, "apps/desktop/dist/engine/questor-engine.exe");
const screenshot = resolve(REPO, "apps/web/e2e/__screenshots__/electron-shell.png");

const electronExe = resolve(REPO, "apps/desktop/node_modules/electron/dist/electron.exe");
const app = await electron.launch({
  executablePath: electronExe,
  args: [resolve(REPO, "apps/desktop")],
  env: {
    ...process.env,
    QUESTOR_ENGINE: engine,
    QUESTOR_WEB_DIST: resolve(WEB, "dist"),
  },
});

const page = await app.firstWindow();
await page.waitForURL(/127\.0\.0\.1:\d+\//, { timeout: 60000 });
await page.getByText("Questor").waitFor({ timeout: 30000 });
await page.getByRole("navigation").waitFor({ timeout: 30000 });
await page.screenshot({ path: screenshot, fullPage: true });
writeFileSync(resolve(WEB, ".e2e-electron-url.txt"), page.url(), "utf8");
console.log("electron url:", page.url());
await app.close();
