// P7 T3：由 protocol/event.schema.json 生成桌面/Web 客户端的 TS 事件类型（C15 单一真源 + 防漂移）。
// 形状改形自参考仓的 generate-protocol（compileFromFile + --check freshness）；输出落 desktop/web/src/generated/。
// 用法：
//   node scripts/generate-protocol.mjs          # 生成/覆盖 event.ts
//   node scripts/generate-protocol.mjs --check   # 比对已生成文件与 schema 现算输出，不一致退出码非零（CI 漂移门）
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { compileFromFile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
// scripts/ 在 desktop/web/ 下：../../.. = 仓库根 questor/。
const schemaPath = resolve(here, "../../../protocol/event.schema.json");
const outputPath = resolve(here, "../src/generated/event.ts");
const banner = "/* AUTO-GENERATED from protocol/event.schema.json. DO NOT EDIT. */";

const generated = await compileFromFile(schemaPath, {
  bannerComment: banner,
  cwd: dirname(schemaPath),
  // 外部事件是 wire 契约：所有属性保留 schema 声明的名字，别被"优化"掉。
  unreachableDefinitions: false,
});

if (process.argv.includes("--check")) {
  const current = await readFile(outputPath, "utf8").catch(() => "");
  if (current !== generated) {
    process.stderr.write(
      "Generated protocol types are stale. Run `npm run generate:protocol`.\n",
    );
    process.exitCode = 1;
  } else {
    process.stdout.write("protocol TS types are up to date.\n");
  }
} else {
  // 目标目录可能尚未建（新面首次生成）；writeFile 不自动建目录，先 mkdir -p。
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, generated, "utf8");
  process.stdout.write(`wrote ${outputPath}\n`);
}
