// 把仓根黄金帧（tests/fixtures/serve_wire/*.json）收进 apps/web，供前端回放测试。
// 单一真源仍是 tests/fixtures/serve_wire；本脚本只做“带校验的复制”。
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "../../../tests/fixtures/serve_wire");
const target = resolve(here, "../src/generated/wire-fixtures.json");
const checkOnly = process.argv.includes("--check");

const files = (await readdir(source)).filter((name) => name.endsWith(".json")).sort();
const fixtures = [];
for (const name of files) {
  fixtures.push(JSON.parse(await readFile(join(source, name), "utf8")));
}
const text = JSON.stringify(fixtures, null, 2) + "\n";

if (checkOnly) {
  const current = await readFile(target, "utf8").catch(() => "");
  if (current !== text) {
    process.stderr.write("wire fixtures are stale; run `node scripts/gen-web-fixtures.mjs`\n");
    process.exitCode = 1;
  }
} else {
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, text, "utf8");
  process.stdout.write(`wrote ${fixtures.length} fixtures to ${target}\n`);
}
