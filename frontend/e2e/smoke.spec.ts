// Phase 8 DoD smoke (quickstart S5): dev-mode register → upload → ready →
// chat → streamed answer + [1] citation → source viewer, all against the
// local compose stack with zero external credentials (docs/local-dev.md §1,
// docs/roadmap.md Phase 8).
import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";

const FIXTURE = fileURLToPath(new URL("./fixtures/sample.pdf", import.meta.url));
const QUESTION = "What is the refund period?";
const CHUNK_TEXT = "The refund period is 30 days from purchase.";

test("smoke: login → upload → ready → chat → cite", async ({ page }) => {
  // -- US1: register (dev mode, any email) → lands on /documents ------------
  const email = `smoke-${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("smoke-pass-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Documents Space" })).toBeVisible();

  // -- US2 validation: non-PDF rejected with a friendly inline error (S2) ----
  const txtProbe = fileURLToPath(new URL("./fixtures/not-a-pdf.txt", import.meta.url));
  await page.setInputFiles('input[type="file"]', txtProbe);
  await expect(page.getByText(/PDF files only/)).toBeVisible();
  await expect(page.getByText("sample.pdf uploaded")).not.toBeVisible();

  // -- US2: upload the fixture via the dropzone ------------------------------
  await page.setInputFiles('input[type="file"]', FIXTURE);
  await expect(page.getByText("sample.pdf uploaded")).toBeVisible({ timeout: 30_000 });

  // Row appears with a queued/processing badge, then advances to Ready
  // without a refresh (3 s polling).
  await expect(page.getByRole("row").filter({ hasText: "sample.pdf" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "sample.pdf" })).toContainText(
    "Ready",
    { timeout: 120_000 },
  );

  // -- US3: new conversation with the ready document -------------------------
  await page.getByRole("link", { name: "New Conversation" }).first().click();
  await expect(page.getByText("Start your first conversation")).toBeVisible();

  const docCheckbox = page.getByRole("checkbox", { name: "Use sample.pdf" });
  await expect(docCheckbox).toBeVisible();
  await docCheckbox.check();

  await page.getByRole("button", { name: "New Conversation" }).click();
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);

  // Context panel mirrors the conversation's selection.
  await expect(page.locator('aside').filter({ hasText: "Context Selection" })).toContainText(
    "sample.pdf",
  );

  // -- Ask: typing indicator → deltas → done with a [1] citation chip --------
  await page.getByRole("textbox", { name: "Message" }).fill(QUESTION);
  await page.getByRole("button", { name: "Send message" }).click();

  // Typing indicator while pending (aria-label "Thinking" on the dots).
  await expect(page.getByLabel("Thinking")).toBeVisible();
  await expect(page.getByRole("status").and(page.getByLabel("Thinking"))).toBeVisible();

  // Streamed answer content arrives; then the citation chip appears when the
  // provider emits its [1] delta (dev stack). The answer text differs by
  // provider: a real model cites the excerpt inline ("…from purchase [1]."),
  // the fake provider streams its canned "Answer for …" text — accept either.
  const chip = page.getByRole("button", {
    name: /\[1\] sample\.pdf p\.1/,
  });
  await expect(chip).toBeVisible({ timeout: 120_000 });
  await expect(page.locator(".whitespace-pre-wrap")).toContainText(
    /The refund period is 30 days from purchase|Answer for/,
  );

  // -- Source viewer: persistent right panel with [1] card (prototype) -------
  await chip.click();
  const card = page.locator("aside").filter({ hasText: "Source Viewer" }).locator("div.overflow-hidden");
  await expect(card.first()).toBeVisible();
  await expect(card.first()).toContainText("sample.pdf");
  await expect(card.first()).toContainText("Page 1");
  await expect(card.first()).toContainText(CHUNK_TEXT);
  await expect(card.first().locator("mark").first()).toBeVisible(); // question-term highlight

  // "Open Document" fetches the signed URL (contract C5).
  await page.locator("aside").filter({ hasText: "Source Viewer" }).getByRole("button", { name: /Open Document/ }).click();
  await page.waitForTimeout(500);
  await page.locator("aside").filter({ hasText: "Source Viewer" }).getByRole("button", { name: "Close source viewer" }).click();
  await expect(page.locator("aside").filter({ hasText: "Source Viewer" })).not.toBeVisible();

  // -- S4: conversation with NO documents blocks the composer (chat.md §6) ---
  await page.goto("/chat");
  await page.getByRole("button", { name: "New Conversation" }).click(); // no selection
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  const composer = page.getByRole("textbox", { name: "Message" });
  await expect(composer).toHaveAttribute("placeholder", "Add documents to this conversation first");
  await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();
  await expect(page.getByText("Add documents to this conversation first (the API rejects questions without selected documents).")).toBeVisible();
});