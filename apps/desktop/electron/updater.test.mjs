import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import updater from "./updater.cjs";

function sandbox() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "questor-updater-"));
  for (const version of ["1.0.0", "1.1.0"]) {
    fs.mkdirSync(path.join(root, "versions", version), { recursive: true });
  }
  fs.writeFileSync(path.join(root, "current.json"), JSON.stringify({ current: "1.0.0", previous: null }));
  return root;
}

test("activate 把旧 current 记为 previous", () => {
  const root = sandbox();
  assert.deepEqual(updater.activate(root, "1.1.0"), { current: "1.1.0", previous: "1.0.0" });
  assert.equal(updater.readPointer(root).current, "1.1.0");
});

test("rollback 切回 previous", () => {
  const root = sandbox();
  updater.activate(root, "1.1.0");
  assert.deepEqual(updater.rollback(root), { current: "1.0.0", previous: null });
});

test("没有 previous 时 rollback 保持不动", () => {
  const root = sandbox();
  assert.deepEqual(updater.rollback(root), { current: "1.0.0", previous: null });
});

test("未知版本拒绝激活", () => {
  const root = sandbox();
  assert.throws(() => updater.activate(root, "9.9.9"), /unknown version/);
});
