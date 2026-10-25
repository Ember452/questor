/** Electron 鐪熷３鍐掔儫锛氬惎鍔?鈫?鎻℃墜 鈫?cookie 鈫?鍔犺浇 apps/web/dist 鈫?鐪嬪埌瀵艰埅銆?*/
import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../../..");
const require = createRequire(import.meta.url);
const playwright = require(resolve(REPO, "apps/web/node_modules/playwright"));
const electron = playwright._electron;

const engine = resolve(REPO, "apps/desktop/dist/engine/questor-engine.exe");
const screenshot = resolve(REPO, "apps/web/e2e/__screenshots__/electron-shell.png");

const app = await electron.launch({
  executablePath: resolve(REPO, "apps/desktop/node_modules/electron/dist/electron.exe"),
  args: [resolve(REPO, "apps/desktop")],
  env: {
    ...process.env,
    QUESTOR_ENGINE: engine,
    QUESTOR_WEB_DIST: resolve(REPO, "apps/web/dist"),
  },
});

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
await app.close();
