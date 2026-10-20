// B14：citation 格式化的单测——**只消费事件、不猜形状**。
//
// 关键判据不是"能画出来"，而是"画不出来的时候也不乱画"：形状不对的条目逐条丢弃、
// 区间反了不算归因、无引用返回空串（前端因此不画节点）。

import { describe, expect, it } from "vitest";

import { citationId, formatCitations, parseCitations } from "./citations";

const entry = { path: "memory/2026-10-01.md", line_start: 3, line_end: 7 };

describe("parseCitations", () => {
  it("keeps well-formed entries in order", () => {
    const parsed = parseCitations({
      citations: { entries: [entry, { ...entry, path: "memory/2026-10-02.md", line_start: 1, line_end: 2 }] },
    });
    expect(parsed.map((e) => e.path)).toEqual(["memory/2026-10-01.md", "memory/2026-10-02.md"]);
    expect(parsed[0]).toEqual({ path: "memory/2026-10-01.md", lineStart: 3, lineEnd: 7, note: null });
  });

  it("drops malformed entries instead of the whole block", () => {
    const parsed = parseCitations({
      citations: {
        entries: [
          entry,
          { path: "", line_start: 1, line_end: 2 }, // 空路径
          { path: "a.md", line_start: 5, line_end: 2 }, // 区间反了
          { path: "b.md", line_start: "3", line_end: 4 }, // 行号不是数字
          null,
          "nope",
        ],
      },
    });
    expect(parsed.map((e) => e.path)).toEqual(["memory/2026-10-01.md"]);
  });

  it("caps entries at the wire maxItems", () => {
    const many = Array.from({ length: 25 }, () => entry);
    expect(parseCitations({ citations: { entries: many } })).toHaveLength(10);
  });

  it("returns nothing for absent or non-object payloads", () => {
    for (const data of [undefined, null, "str", 7, {}, { citations: null }, { citations: { entries: "x" } }]) {
      expect(parseCitations(data)).toEqual([]);
    }
  });

  it("keeps a bounded note and drops an empty one", () => {
    const withNote = parseCitations({ citations: { entries: [{ ...entry, note: "user stated" }] } });
    expect(withNote[0].note).toBe("user stated");
    const blank = parseCitations({ citations: { entries: [{ ...entry, note: "" }] } });
    expect(blank[0].note).toBeNull();
  });
});

describe("formatCitations", () => {
  it("renders entry-level ids the user can trace back", () => {
    expect(formatCitations({ citations: { entries: [entry] } })).toBe("来源：memory/2026-10-01.md:3-7");
    expect(
      formatCitations({
        citations: { entries: [entry, { ...entry, path: "MEMORY.md", line_start: 1, line_end: 1 }] },
      }),
    ).toBe("来源：memory/2026-10-01.md:3-7 · MEMORY.md:1-1");
  });

  it("is an empty string when there is nothing to attribute", () => {
    expect(formatCitations({})).toBe("");
    expect(formatCitations({ citations: { entries: [] } })).toBe("");
    expect(formatCitations(undefined)).toBe("");
  });

  it("is pure and does not mutate its input", () => {
    // 只消费事件：不改写入参。真不变量（不发命令、不 fetch）由 check_thin_client 机守，
    // 不在这里拿脆弱的路径字符串模拟。
    const before = { citations: { entries: [entry] } };
    const snapshot = JSON.stringify(before);
    formatCitations(before);
    expect(JSON.stringify(before)).toBe(snapshot);
    const again = formatCitations(before);
    expect(again).toBe(formatCitations(before)); // 同输入同输出
  });

  it("builds the same id shape the server uses", () => {
    expect(citationId({ path: "p.md", lineStart: 0, lineEnd: 0, note: null })).toBe("p.md:0-0");
  });
});
