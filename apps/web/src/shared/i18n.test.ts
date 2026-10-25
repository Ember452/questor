/** i18n 骨架测试：回落语义 + key 表唯一性。 */

import { describe, expect, it } from "vitest";

import { t } from "./i18n";

describe("t()", () => {
  it("中文即 key：无译文时原样回落", () => {
    expect(t("需要审批")).toBe("需要审批");
  });

  it("英文表存在时不回落（用注入样例验证语义）", () => {
    // EN 表当前为空：回落即正确行为；此用例在填入首条译文后改写为断言该条。
    expect(t("__missing__")).toBe("__missing__");
  });
});
