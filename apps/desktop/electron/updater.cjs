/**
 * 版本目录 + current.json 指针的更新器：新版本启动失败 → 切回 previous。
 * 纯 Node，不依赖 Electron，因此可以被 node --test 直接覆盖。
 */
const fs = require("node:fs");
const path = require("node:path");

function readPointer(root) {
  const file = path.join(root, "current.json");
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!data.current) throw new Error("current pointer missing");
  return data;
}

function writePointer(root, pointer) {
  fs.writeFileSync(path.join(root, "current.json"), JSON.stringify(pointer, null, 2) + "\n", "utf8");
}

/** 激活新版本：旧 current 变成 previous。 */
function activate(root, version) {
  const target = path.join(root, "versions", version);
  if (!fs.existsSync(target)) throw new Error(`unknown version ${version}`);
  const previous = fs.existsSync(path.join(root, "current.json")) ? readPointer(root).current : null;
  writePointer(root, { current: version, previous });
  return { current: version, previous };
}

/** 启动失败时回滚；没有 previous 则不回滚（保持失败可见）。 */
function rollback(root) {
  const pointer = readPointer(root);
  if (!pointer.previous) return pointer;
  const reverted = { current: pointer.previous, previous: null };
  writePointer(root, reverted);
  return reverted;
}

module.exports = { activate, rollback, readPointer };
