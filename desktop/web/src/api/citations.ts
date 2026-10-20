// B14：行级 citation 的**纯格式化**（只消费事件，不发命令、不解释语义）。
//
// 为什么单独一个文件：`message_completed.citations` 是 wire 载荷（`unknown`），前端要做的是
// "把可信形状挑出来画上去"，不是"自己推断引用了什么"。所有丢弃规则与服务端
// `contracts/memory.citation_from_payload` 同向：**形状不对就丢掉这一条，不猜、不整块作废**。
// 本文件不许出现 fetch、不许列事件类型名（thin-client 三不变量由守卫机守）。

export type CitationEntry = {
  path: string;
  lineStart: number;
  lineEnd: number;
  note: string | null;
};

const MAX_ENTRIES = 10; // 与 event.schema.json 的 maxItems / CITATION_MAX_ENTRIES 同源
const MAX_PATH = 288; // 与 entry_id 的 maxLength 同源

function isBoundedString(value: unknown, max: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= max;
}

function isLine(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

/** 从 `message_completed` 的 data 里取引用条目；任何形状不对的条目**逐条丢弃**。 */
export function parseCitations(data: unknown): CitationEntry[] {
  if (data === null || typeof data !== "object") return [];
  const raw = (data as { citations?: unknown }).citations;
  if (raw === null || typeof raw !== "object") return [];
  const entries = (raw as { entries?: unknown }).entries;
  if (!Array.isArray(entries)) return [];
  const out: CitationEntry[] = [];
  for (const item of entries.slice(0, MAX_ENTRIES)) {
    if (item === null || typeof item !== "object") continue; // 非对象条目：丢掉，不整体失败
    const rec = item as { path?: unknown; line_start?: unknown; line_end?: unknown; note?: unknown };
    if (!isBoundedString(rec.path, MAX_PATH)) continue;
    if (!isLine(rec.line_start) || !isLine(rec.line_end)) continue;
    if (rec.line_end < rec.line_start) continue; // 区间反了=假归因，宁缺
    const note = typeof rec.note === "string" && rec.note.length > 0 ? rec.note : null;
    out.push({ path: rec.path, lineStart: rec.line_start, lineEnd: rec.line_end, note });
  }
  return out;
}

/** 条目级 id（与服务端 `path:start-end` 同一形状，用于"点开看是哪一行"）。 */
export function citationId(entry: CitationEntry): string {
  return `${entry.path}:${entry.lineStart}-${entry.lineEnd}`;
}

/** 一行可读来源；无引用时返回空串（调用方据此不画节点，不画"来源：（无）"）。 */
export function formatCitations(data: unknown): string {
  const entries = parseCitations(data);
  if (entries.length === 0) return "";
  return "来源：" + entries.map((entry) => citationId(entry)).join(" · ");
}
