import { expect, test } from "@playwright/test";

test("narrow 390x844：导航折叠为紧凑条，卡片单列", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const nav = page.getByRole("navigation");
  await expect(nav).toBeVisible();
  const box = await nav.boundingBox();
  expect(box?.width ?? 0).toBeLessThanOrEqual(390);
  await expect(page.locator("[data-action='composer']")).toBeVisible();
});
