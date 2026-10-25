import { expect, test } from "@playwright/test";

const MATRIX = [
  { name: "light-1280", scheme: "light", width: 1280, height: 720 },
  { name: "dark-1280", scheme: "dark", width: 1280, height: 720 },
  { name: "light-390", scheme: "light", width: 390, height: 844 },
  { name: "dark-390", scheme: "dark", width: 390, height: 844 },
] as const;

for (const entry of MATRIX) {
  test(`design matrix ${entry.name}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: entry.scheme });
    await page.setViewportSize({ width: entry.width, height: entry.height });
    await page.goto("/?demo=1");
    await expect(page.getByText("Questor")).toBeVisible();
    await expect(page).toHaveScreenshot(`matrix-${entry.name}.png`, { maxDiffPixels: 200 });
  });
}
