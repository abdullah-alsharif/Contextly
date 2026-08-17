// Phase 12 replace-restore regression (migration 0008): deleting a finalized
// replacement re-queues the outdated version — no manual refresh needed.
import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";

const FIXTURE = fileURLToPath(new URL("./fixtures/sample.pdf", import.meta.url));

test("replace: deleting the ready replacement re-queues the outdated version in place", async ({ page }) => {
  const email = `replace-${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("smoke-pass-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Documents Space" })).toBeVisible();

  await page.setInputFiles('input[type="file"]', FIXTURE);
  await expect(page.getByText("sample.pdf uploaded")).toBeVisible({ timeout: 30_000 });
  const row = page.getByRole("row").filter({ hasText: "sample.pdf" });
  await expect(row).toContainText("Ready", { timeout: 120_000 });

  // same file again → "Update existing" → the old version flips to Outdated
  await page.setInputFiles('input[type="file"]', FIXTURE);
  await page.getByRole("button", { name: /Update existing/ }).click();
  const rows = page.getByRole("row").filter({ hasText: "sample.pdf" });
  // the new row is prepended; wait for both rows so the first one is the replacement
  await expect(rows).toHaveCount(2, { timeout: 30_000 });
  await expect(rows.first()).toContainText("Ready", { timeout: 120_000 });
  await expect(rows.nth(1)).toContainText("Outdated");

  // delete the ready replacement → the outdated row re-queues in place
  await rows.first().getByRole("button", { name: "Delete sample.pdf" }).click();
  await rows.first().getByRole("button", { name: "Confirm" }).click();
  // the delete response drops the deleted row; the survivor may briefly show
  // Queued before the worker rebuilds it
  const onlyRow = page.getByRole("row").filter({ hasText: "sample.pdf" });
  await expect(onlyRow).toHaveCount(1, { timeout: 30_000 });
  await expect(onlyRow).not.toContainText("Outdated", { timeout: 10_000 });
  await expect(onlyRow).toContainText("Ready", { timeout: 120_000 });
});
