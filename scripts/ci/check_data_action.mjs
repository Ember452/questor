// data-action 审计：所有 <button> 必须有 data-action（design-qa 的一部分）。
import { readdir, readFile } from "node:fs/promises";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../apps/web/src");
const problems = [];

async function walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) await walk(path);
    else if (path.endsWith(".tsx")) {
      const text = await readFile(path, "utf8");
      for (const [index, line] of text.split("\n").entries()) {
        if (line.includes("<button") && !line.includes("data-action") && !line.trim().startsWith("*")) {
          // 多行属性：向后看 4 行
          const window = text.split("\n").slice(index, index + 5).join(" ");
          if (!window.includes("data-action")) problems.push(`${path}:${index + 1}`);
        }
      }
    }
  }
}

await walk(root);
if (problems.length) {
  process.stderr.write("buttons without data-action:\n" + problems.join("\n") + "\n");
  process.exit(1);
}
process.stdout.write("data-action: OK\n");
