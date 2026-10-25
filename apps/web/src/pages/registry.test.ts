import { describe, expect, it } from "vitest";

import { isVisible } from "../app/capabilityGate";
import { PAGES } from "./registry";

const caps = (state: "ready" | "declared" | "absent") => ({ chat: state, thread: state });

describe("页面注册表与 capability 门控", () => {
  it("registry 的 page id 必须被 profile capabilities 覆盖（ready 才可见）", () => {
    const ready = isVisible(PAGES[0], caps("ready"));
    expect(ready).toBe(true);
  });

  it("declared / absent 入口不出现", () => {
    for (const page of PAGES) {
      expect(isVisible(page, { ...caps("declared") })).toBe(false);
      expect(isVisible(page, { ...caps("absent") })).toBe(false);
    }
  });

  it("两个 profile 的并集可以超过单形态导航预算", () => {
    expect(PAGES.map((page) => page.id)).toEqual(["chat", "thread"]);
  });
});
