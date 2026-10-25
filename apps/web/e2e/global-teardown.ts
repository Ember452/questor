/** Playwright 拆机：杀掉 global-setup 起的 studio 宿主与 preview。 */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PIDS = resolve(WEB, ".e2e-pids.json");

export default function globalTeardown(): void {
  if (!existsSync(PIDS)) return;
  const { engine, preview } = JSON.parse(readFileSync(PIDS, "utf8")) as {
    engine: number;
    preview: number;
  };
  for (const pid of [preview, engine]) {
    try {
      if (process.platform === "win32") {
        spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
      } else {
        process.kill(pid, "SIGTERM");
      }
    } catch {
      /* already gone */
    }
  }
}
