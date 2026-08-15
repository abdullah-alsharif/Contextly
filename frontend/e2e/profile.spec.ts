// Profile flow (dev mode): register with a display name → chip shows the name
// (never the email) → edit in /settings (PATCH /auth/me) → chip updates
// instantly via "profile:updated". Zero external credentials (docs/local-dev.md §1).
import { expect, test } from "@playwright/test";

test("profile: register with name → chip → edit in settings → chip updates", async ({
  page,
}) => {
  const email = `profile-${Date.now()}@example.com`;
  const name = `Persona ${Date.now()}`;
  const renamed = `${name} Jr`;

  // -- Register with a full name; chip provisions from the token claim -------
  await page.goto("/register");
  await page.getByLabel("Full name").fill(name);
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("smoke-pass-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Documents Space" })).toBeVisible();

  const sidebar = page.getByRole("complementary").first();
  await expect(sidebar.getByText(name, { exact: true })).toBeVisible();
  await expect(sidebar.getByText(email, { exact: true })).not.toBeVisible();

  // -- Settings: name pre-filled, email read-only ----------------------------
  // Settings moved into the account menu popover.
  await sidebar.getByRole("button", { name: "Open account menu" }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  const nameInput = page.getByLabel("Full name");
  await expect(nameInput).toHaveValue(name);
  await expect(page.getByLabel("Email")).toBeDisabled();

  await nameInput.fill(renamed);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status").and(page.getByText("Saved."))).toBeVisible();
  await expect(nameInput).toHaveValue(renamed);

  // -- Chip updates instantly (profile:updated event) — no poll wait, no
  // -- navigation or refresh -------------------------------------------------
  await expect(sidebar.getByText(renamed, { exact: true })).toBeVisible({
    timeout: 3_000,
  });
  await expect(sidebar.getByText(name, { exact: true })).not.toBeVisible();

  // -- Navigating away keeps the updated name -------------------------------
  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page.getByRole("heading", { name: "Documents Space" })).toBeVisible();
  await expect(sidebar.getByText(renamed, { exact: true })).toBeVisible();
  await expect(sidebar.getByText(name, { exact: true })).not.toBeVisible();
});
