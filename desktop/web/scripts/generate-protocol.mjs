// P7 T3：由 protocol/event.schema.json 生成桌面/Web 客户端的 TS 事件类型（C15 单一真源 + 防漂移）。
// 形状改形自参考仓的 generate-protocol（compileFromFile + --check freshness）；输出落 desktop/web/src/generated/。
// 用法：
//   node scripts/generate-protocol.mjs          # 生成/覆盖 event.ts
//   node scripts/generate-protocol.mjs --check   # 比对已生成文件与 schema 现算输出，不一致退出码非零（CI 漂移门）
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { compile, compileFromFile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
// scripts/ 在 desktop/web/ 下：../../.. = 仓库根 questor/。
const schemaPath = resolve(here, "../../../protocol/event.schema.json");
const outputPath = resolve(here, "../src/generated/event.ts");
const banner = "/* AUTO-GENERATED from protocol/event.schema.json. DO NOT EDIT. */";
// §6-5：进程级 sidecar_status 面（独立于 per-run 信封），单独生成一份 TS 类型。
const statusSchemaPath = resolve(here, "../../../protocol/sidecar_status.schema.json");
const statusOutputPath = resolve(here, "../src/generated/sidecarStatus.ts");
const statusBanner = "/* AUTO-GENERATED from protocol/sidecar_status.schema.json. DO NOT EDIT. */";

const toPascal = (snake) =>
  snake.split("_").map((s) => s[0].toUpperCase() + s.slice(1)).join("");

// 顶层信封（判别式 type 联合）。compileFromFile 会把 data 塔成 {[k:string]:unknown}——
// 故另为每个 $defs 编译**字段级具名 payload 接口**，使 check:protocol 对字段增删/改名敏感（§6-4b）。
const envelopeTs = await compileFromFile(schemaPath, {
  bannerComment: banner,
  cwd: dirname(schemaPath),
  unreachableDefinitions: false,
});

const schema = JSON.parse(await readFile(schemaPath, "utf8"));
const dataInterfaces = [];
for (const [name, def] of Object.entries(schema.$defs ?? {})) {
  const { $schema: _drop, ...rest } = def;
  const tsName = `${toPascal(name)}Data`;
  const body = await compile({ ...rest, additionalProperties: rest.additionalProperties ?? false }, tsName, {
    bannerComment: "",
    cwd: dirname(schemaPath),
    unreachableDefinitions: false,
  });
  dataInterfaces.push(body.trim());
}

const generated =
  envelopeTs +
  "\n// ── per-type event data payloads (field-level; a schema field change not reflected here fails --check) ──\n" +
  dataInterfaces.join("\n") +
  "\n";

// §6-5：把 sidecar_status.schema.json 编成具名 TS 类型（state 枚举→字面量联合）；
// 改 schema 不重生成则 --check 判红，与 Python 侧字段级门同经同纬。
const statusSchema = JSON.parse(await readFile(statusSchemaPath, "utf8"));
const { $schema: _dropSchema, $id: _dropId, title: _dropTitle, ...statusRest } = statusSchema;
const statusGenerated =
  statusBanner +
  "\n" +
  (await compile(statusRest, "SidecarStatus", {
    bannerComment: "",
    cwd: dirname(statusSchemaPath),
    unreachableDefinitions: false,
  }));

const outputs = [
  { path: outputPath, content: generated },
  { path: statusOutputPath, content: statusGenerated },
];

if (process.argv.includes("--check")) {
  let stale = false;
  for (const { path, content } of outputs) {
    const current = await readFile(path, "utf8").catch(() => "");
    if (current !== content) {
      process.stderr.write(`Generated protocol types are stale for ${path}. Run \`npm run generate:protocol\`.\n`);
      stale = true;
    }
  }
  if (stale) {
    process.exitCode = 1;
  } else {
    process.stdout.write("protocol TS types are up to date.\n");
  }
} else {
  // 目标目录可能尚未建（新面首次生成）；writeFile 不自动建目录，先 mkdir -p。
  for (const { path, content } of outputs) {
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, content, "utf8");
    process.stdout.write(`wrote ${path}\n`);
  }
}
