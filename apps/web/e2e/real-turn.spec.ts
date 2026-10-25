/** 真回合 e2e：stub LLM 驱动 submit → 审批 → 工具执行 → 收尾文本。 */

import { expect, test } from "@playwright/test";

test("真实链路：提交 → 审批卡放行 → 工具卡 → 最终回复", async ({ page }) => {
  await page.goto("/");

  // 提交一句话（composer 回车即发送）。
  await page.locator('[data-action="composer"]').fill("请运行回显测试");
  await page.locator('[data-action="composer"]').press("Enter");

  // 审批卡出现（Bash 默认需要确认），放行。
  await expect(page.getByText("需要审批")).toBeVisible({ timeout: 30000 });
  await page.locator('[data-action="approve"]').click();

  // 工具卡显示 Bash 与执行结果，最终 say 收到 stub 的固定文本。
  await expect(page.locator('[data-card="tool"]')).toContainText("bash", { timeout: 30000 });
  await expect(page.getByText("questor-stub-ok")).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("工具结果已收到，测试通过。")).toBeVisible({ timeout: 30000 });

  // 回合收口：状态回到空闲。
  await expect(page.locator("header span").last()).toContainText("空闲", { timeout: 30000 });
});
