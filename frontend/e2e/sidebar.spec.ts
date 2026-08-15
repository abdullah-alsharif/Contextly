// Sidebar collapse e2e: the desktop column toggles between 272px and a 64px
// icon rail, labels hide, icon tooltips appear on hover, and the choice
// survives a reload. Registration is real (dev-mode backend); the rail needs
// no conversations to exercise.
import { expect, test } from "@playwright/test";

test("sidebar: collapse to an icon rail with tooltips, persisted", async ({ page }) => {
  const email = `sbcollapse-${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("smoke-pass-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Documents Space" })).toBeVisible();

  const sidebar = page.getByRole("complementary").first();
  await expect(sidebar).toHaveCSS("width", "272px");
  await expect(sidebar.getByText("New Conversation")).toBeVisible();
  await expect(sidebar.getByText("Contextly")).toBeVisible();

  // Collapse: rail only — the label spans are gone (the remaining "New
  // Conversation" text is the hidden tooltip).
  await sidebar.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(sidebar).toHaveCSS("width", "64px");
  await expect(sidebar.getByText("New Conversation")).toHaveCSS("opacity", "0");
  await expect(sidebar.getByText("Contextly")).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "Documents" })).toBeVisible();

  // Hovering an icon reveals its tooltip; moving away hides it again.
  await sidebar.getByRole("link", { name: "Documents" }).hover();
  await expect(sidebar.getByText("Documents").last()).toHaveCSS("opacity", "1");
  await page.mouse.move(400, 300);
  await expect(sidebar.getByText("Documents").last()).toHaveCSS("opacity", "0");

  // The rail state survives a reload.
  await page.reload();
  const sidebarAfterReload = page.getByRole("complementary").first();
  await expect(sidebarAfterReload).toHaveCSS("width", "64px");

  // Clicking rail whitespace (the empty flex space, not a control) expands.
  await page.mouse.click(32, 350);
  await expect(sidebarAfterReload).toHaveCSS("width", "272px");
  await expect(sidebarAfterReload.getByText("New Conversation").first()).toBeVisible();
  await expect(sidebarAfterReload.getByText("Contextly")).toBeVisible();
});
