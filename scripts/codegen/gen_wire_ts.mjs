// app-wire 的 TypeScript 侧生成器。
//
// 单一真源是 protocol/app-wire.schema.json；本脚本只做 schema → TS，
// 输出文件头写明"这是契约，不是顺手类型"。阶段 1 落在 protocol/_gen/，
// apps/web 在 4a 直接消费同一个生成物。
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const schemaPath = process.argv.includes("--schema")
  ? process.argv[process.argv.indexOf("--schema") + 1]
  : resolve(repo, "protocol/app-wire.schema.json");
const outPath = process.argv.includes("--out")
  ? process.argv[process.argv.indexOf("--out") + 1]
  : resolve(repo, "protocol/_gen/app-wire.ts");
const checkOnly = process.argv.includes("--check");

const banner = `/**
 * AUTO-GENERATED from protocol/app-wire.schema.json. DO NOT EDIT.
 *
 * This file is the contract, not a convenience shape: every field here must be
 * carried by the Python side (serve/wire_types.py) or the mirror guard fails.
 */`;

const schema = JSON.parse(await readFile(schemaPath, "utf8"));
const generated = await compile(schema, "AppWire", {
  bannerComment: "",
  additionalProperties: false,
  declareExternallyReferenced: true,
  enableConstEnums: false,
  format: true,
  style: { singleQuote: false },
});
const text = `${banner}\n\n${generated}`;

if (checkOnly) {
  let current = "";
  try {
    current = await readFile(outPath, "utf8");
  } catch {
    current = "";
  }
  if (current === text) {
    process.exit(0);
  }
  const expected = text.split("\n");
  const actual = current.split("\n");
  const limit = Math.max(expected.length, actual.length);
  for (let index = 0; index < limit; index += 1) {
    const want = expected[index] ?? "<missing>";
    const have = actual[index] ?? "<missing>";
    if (want !== have) {
      process.stderr.write(`gen_wire_ts: ${outPath}:${index + 1}: generated file is stale\n`);
      process.stderr.write(`  expected: ${want}\n  actual:   ${have}\n`);
      break;
    }
  }
  process.exit(1);
}

await (await import("node:fs/promises")).mkdir(dirname(outPath), { recursive: true });
await writeFile(outPath, text, "utf8");
process.stdout.write(`gen_wire_ts: wrote ${outPath}\n`);
