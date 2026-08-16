// Context panel + add-documents flows (docs/frontend-design.md §4): desktop
// adds/removes via the account-wide Context Selection panel; below lg the
// composer's + opens the picker modal. Count, search, All/Selected filter,
// Select/Deselect all, and empty states covered against the local compose
// stack (dev-mode register + upload → ready, like smoke).
import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";

const FIXTURE = fileURLToPath(new URL("./fixtures/sample.pdf", import.meta.url));
const usingRow = (page: import("@playwright/test").Page) =>
  page.locator("div").filter({ hasText: /^Using:/ });

test("context: desktop panel manages selection, mobile picker adds", async ({
  page,
}) => {
  // -- register + upload one ready document --------------------------------
  await page.goto("/register");
  await page.getByLabel("Email address").fill(`ctx-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("smoke-pass-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Documents Space" })).toBeVisible();
  await page.setInputFiles('input[type="file"]', FIXTURE);
  await expect(page.getByText("sample.pdf uploaded")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("row").filter({ hasText: "sample.pdf" })).toContainText(
    "Ready",
    { timeout: 120_000 },
  );

  // -- entry page: nothing selected -----------------------------------------
  await page.getByRole("link", { name: "New Conversation" }).first().click();
  await expect(page.getByText("Start your first conversation")).toBeVisible();

  const panel = page.locator("aside").filter({ hasText: "Context Selection" });
  const docCheckbox = page.getByRole("checkbox", { name: "Use sample.pdf" });

  // Live count starts at 0 of 1 selected.
  await expect(panel.getByText("0 of 1 selected")).toBeVisible();

  // Select all → checked + count 1 of 1 + label flips to Deselect all.
  await panel.getByRole("button", { name: "Select all" }).click();
  await expect(docCheckbox).toBeChecked();
  await expect(panel.getByText("1 of 1 selected")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Deselect all" })).toBeVisible();

  // Selected filter shows the row; Deselect all → nothing-selected state.
  await panel.getByRole("button", { name: "Selected" }).click();
  await expect(docCheckbox).toBeVisible();
  await panel.getByRole("button", { name: "Deselect all" }).click();
  await expect(panel.getByText("Nothing selected")).toBeVisible();

  // Empty-state action selects everything and the list comes back.
  await panel.getByRole("button", { name: "Select all documents" }).click();
  await expect(docCheckbox).toBeChecked();
  await expect(panel.getByText("1 of 1 selected")).toBeVisible();

  // -- search: match keeps the row, no match shows the empty state ----------
  const search = page.getByRole("textbox", { name: "Search documents" });
  await search.fill("zzz");
  await expect(panel.getByText("No matches")).toBeVisible();
  await panel
    .getByText("No matches")
    .locator("..")
    .getByRole("button", { name: "Clear search" })
    .click();
  await expect(panel.getByText(/No matches/)).not.toBeVisible();
  await expect(docCheckbox).toBeVisible();

  // -- desktop conversation: filter defaults to Selected ----------------------
  // Conversation 1 carries the selection (US3 AC5). The panel lists every
  // ready doc but starts on the Selected filter → the checked doc shows.
  await page.getByRole("button", { name: "New Conversation", exact: true }).click();
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  await expect(panel.getByRole("button", { name: "Selected" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(panel.getByText("1 of 1 selected")).toBeVisible();
  await expect(docCheckbox).toBeChecked();
  // The composer's + stays hidden on desktop (the panel owns context there).
  await expect(page.getByRole("button", { name: "Add documents" })).not.toBeVisible();

  // -- a fresh conversation starts Selected with nothing in context ----------
  await page.goto("/chat");
  await page.getByRole("button", { name: "New Conversation", exact: true }).click();
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  await expect(panel.getByRole("button", { name: "Selected" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(panel.getByText("Nothing selected")).toBeVisible();

  // Switching to All reveals every ready doc — checking adds it to the
  // conversation.
  await panel.getByRole("button", { name: "All", exact: true }).click();
  await expect(docCheckbox).not.toBeChecked();
  await docCheckbox.check();
  await expect(panel.getByText("1 of 1 selected")).toBeVisible();
  await expect(page.getByText("Using:", { exact: true })).toBeVisible();
  await expect(usingRow(page).getByText("sample.pdf", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Message" }).fill("hello");
  await expect(page.getByRole("button", { name: "Send message" })).toBeEnabled();

  // -- mobile: composer + opens the picker (desktop panel hidden) -------------
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Add documents" })).toBeVisible();
  await page.getByRole("button", { name: "Add documents" }).click();
  const picker3 = page.getByRole("dialog", { name: "Add documents" });
  await expect(picker3).toBeVisible();
  await expect(picker3.getByText("Everything is already included")).toBeVisible();
  await expect(picker3.getByRole("button", { name: "Add", exact: true })).toBeDisabled();
  await picker3.getByRole("button", { name: "Close add documents" }).click();
  await expect(picker3).not.toBeVisible();

  // -- mobile picker in an empty conversation: add unblocks the composer -----
  await page.goto("/chat");
  await page.getByRole("button", { name: "New Conversation", exact: true }).click();
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();

  await page.getByRole("button", { name: "Add documents" }).click();
  const picker4 = page.getByRole("dialog", { name: "Add documents" });
  await expect(picker4).toBeVisible();
  await expect(picker4.getByText("1 ready document available")).toBeVisible();
  await expect(picker4.getByRole("button", { name: "Add", exact: true })).toBeDisabled();

  // Search narrows the picker list.
  await picker4.getByRole("textbox", { name: "Search documents" }).fill("zzz");
  await expect(picker4.getByText("No matches")).toBeVisible();
  await picker4.getByRole("textbox", { name: "Search documents" }).fill("");
  await expect(picker4.getByRole("checkbox", { name: "Add sample.pdf" })).toBeVisible();

  await picker4.getByRole("checkbox", { name: "Add sample.pdf" }).check();
  await picker4.getByRole("button", { name: "Add (1)" }).click();
  await expect(picker4).not.toBeVisible();

  // Composer is unblocked and mirrors the new selection.
  await expect(page.getByText(/Using:/)).toBeVisible();
  await expect(usingRow(page).getByText("sample.pdf", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Message" }).fill("hello");
  await expect(page.getByRole("button", { name: "Send message" })).toBeEnabled();
});
