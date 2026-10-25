/** design-qa：核心前景/背景对必须满足 WCAG 对比度；改坏色值即红。 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const tokens = readFileSync(resolve(__dirname, "tokens.reasonix.css"), "utf8");

/** 4a 外壳与卡片实际使用的两对颜色（与 App.module.css / cards.module.css 一致）。 */
const PAIRS: Array<[string, string, number]> = [
  ["#d6dde6", "#101418", 4.5],
  ["#8b9aab", "#101418", 4.5],
];

function luminance(hex: string): number {
  const value = hex.replace("#", "");
  const full = value.length === 3 ? value.split("").map((c) => c + c).join("") : value;
  const [r, g, b] = [0, 2, 4].map((offset) => parseInt(full.slice(offset, offset + 2), 16) / 255);
  const channel = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function ratio(fg: string, bg: string): number {
  const [a, b] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}

describe("design-qa contrast", () => {
  it("正文/次要文字对背景 ≥ 4.5", () => {
    for (const [fg, bg, minimum] of PAIRS) {
      expect(ratio(fg, bg)).toBeGreaterThanOrEqual(minimum);
    }
  });

  it("自证：同色对比度为 1（改坏色值会掉到阈值以下）", () => {
    expect(ratio("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    expect(ratio("#ffffff", "#ffffff")).toBeLessThan(4.5);
  });

  it("设计法典 token 文件存在 --text 定义（迁移未断链）", () => {
    expect(tokens).toMatch(/--text\s*:/);
  });
});
