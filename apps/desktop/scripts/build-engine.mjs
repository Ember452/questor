// PyInstaller onedir 构建：产物在 apps/desktop/dist/engine（拒绝 onefile）。
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const spec = resolve(root, "packaging/questor-engine.spec");
const dist = resolve(root, "dist");
const args = ["--noconfirm", "--distpath", dist, spec];

function run(command, argv) {
  return spawnSync(command, argv, { stdio: "inherit", cwd: resolve(root, "../..") });
}

let result = run("pyinstaller", args);
if (result.error || result.status === null) {
  // CI/uv 环境下 pyinstaller 只存在于虚拟环境，不在 PATH：走 uv run。
  result = run("uv", ["run", "pyinstaller", ...args]);
}
if (result.status !== 0) {
  process.stderr.write("pyinstaller failed: install it with `uv sync --extra dev`\n");
  process.exit(result.status ?? 1);
}
