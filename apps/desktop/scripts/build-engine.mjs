// PyInstaller onedir 构建：产物在 apps/desktop/dist/engine（拒绝 onefile）。
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const spec = resolve(root, "packaging/questor-engine.spec");
const result = spawnSync("pyinstaller", ["--noconfirm", "--distpath", resolve(root, "dist"), spec], {
  stdio: "inherit",
  cwd: resolve(root, "../.."),
});
if (result.status !== 0) {
  process.stderr.write("pyinstaller failed: install it with `uv sync --extra dev`\n");
  process.exit(result.status ?? 1);
}
