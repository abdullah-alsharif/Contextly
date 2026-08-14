// Search chats e2e: recents on empty query, title + message-content search,
// skeleton loading (no stale results), query persistence via Cmd+K, Clear /
// Close / Escape / overlay dismissal, no-results state, and infinite scroll
// pagination (5 at a time) against a mocked page API. The upload + answer
// flow uses the real backend; zero external credentials.
import { expect, test } from "@playwright/test";
import { join } from "node:path";

const FIXTURE = join(__dirname, "fixtures", "sample.pdf");

async function register(page: import("@playwright/test").Page, prefix: string) {
  const email = `${prefix}-${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("smoke-pass-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Documents Space" })).toBeVisible();
}

test("search: content match → restore → close → no-results", async ({ page }) => {
  // Register + upload + ready + conversation with the document.
  await register(page, "search");
  await page.setInputFiles('input[type="file"]', FIXTURE);
  await expect(page.getByText("sample.pdf uploaded")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("row").filter({ hasText: "sample.pdf" })).toContainText(
    "Ready",
    { timeout: 120_000 },
  );

  await page.getByRole("link", { name: "New Conversation" }).first().click();
  await page.getByRole("checkbox", { name: "Use sample.pdf" }).check();
  await page.getByRole("button", { name: "New Conversation" }).click();
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  const conversationUrl = page.url();

  await page.getByRole("textbox", { name: "Message" }).fill("What is the refund period?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("button", { name: /\[1\] sample\.pdf p\.1/ })).toBeVisible({
    timeout: 120_000,
  });

  const sidebar = page.getByRole("complementary").first();
  const dialog = page.getByRole("dialog", { name: "Search conversations" });
  const input = dialog.getByRole("textbox", { name: "Search conversations" });

  // Empty query lists the most recent chats, input autofocused.
  await sidebar.getByRole("button", { name: "Search conversations" }).click();
  await expect(input).toBeFocused();
  await expect(dialog.getByText("Recent")).toBeVisible();
  const recentRow = dialog
    .locator("[data-search-row]")
    .filter({ hasText: "What is the refund period?" });
  await expect(recentRow).toBeVisible({ timeout: 15_000 }); // sidebar poll

  // Skeleton shows while the response is held back ~800ms.
  await page.route("**/api/v1/conversations?q=*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 800));
    await route.continue();
  });
  await input.fill("refund");
  await expect(dialog.locator("[data-skeleton-row]")).toHaveCount(4);

  // Message-content match with a preview line + highlight.
  const result = dialog
    .locator("[data-search-row]")
    .filter({ hasText: "What is the refund period?" });
  await expect(result).toBeVisible();
  await expect(result).toContainText("The refund period is 30 days");
  await expect(result.locator("span.font-semibold").first()).toHaveText("refund");
  await expect(result.locator("time")).toHaveText("Today");
  await expect(dialog.locator("[data-skeleton-row]")).toHaveCount(0);

  // Search rows are plain — no pin/⋮ icons.
  await expect(dialog.getByRole("button", { name: /Options for/ })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: /Pin / })).toHaveCount(0);

// Opening the result keeps the same conversation; Cmd+K restores the list.
  await result.click();
  await expect(page).toHaveURL(conversationUrl);
  await expect(dialog).not.toBeVisible();
  await page.keyboard.press("Meta+k");
  await expect(input).toHaveValue("refund");
  await expect(dialog.locator("[data-search-row]")).toHaveCount(1);

  // Close search dismisses the popup and resets the query.
  await dialog.getByRole("button", { name: "Close search" }).click();
  await expect(dialog).not.toBeVisible();
  await sidebar.getByRole("button", { name: "Search conversations" }).click();
  await expect(input).toHaveValue("");
  await expect(dialog.getByText("Recent")).toBeVisible();

  // Escape dismisses too.
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await sidebar.getByRole("button", { name: "Search conversations" }).click();

  // No results state: centered search icon + "No results".
  await input.fill("zzzznope");
  await expect(dialog.getByRole("paragraph").filter({ hasText: "No results" })).toBeVisible();

  // Clear resets to the empty search state, keeping the popup open.
  await dialog.getByRole("button", { name: "Clear search" }).click();
  await expect(input).toHaveValue("");
  await expect(dialog.getByText("Recent")).toBeVisible();

  // Overlay click closes the popup.
  await page.mouse.click(20, 20);
  await expect(dialog).not.toBeVisible();
});

test.describe("infinite scroll", () => {
  // Short viewport so 5 rows overflow the popup and the scroll actually
  // brings the load-more sentinel into view.
  test.use({ viewport: { width: 1280, height: 400 } });

  test("search: infinite scroll fetches 5 at a time", async ({ page }) => {
    // Mock the page API so pagination is deterministic: 7 matches, 5 + 2.
    const rows = Array.from({ length: 7 }, (_, index) => ({
      id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      title: `Star plan doc ${index}`,
      pinned: false,
      archived: false,
      created_at: "2026-01-01T10:00:00Z",
      updated_at: `2026-01-0${index + 1}T10:00:00Z`,
      preview: `Preview line ${index} about the star plan.`,
    }));
    await page.route("**/api/v1/conversations?q=*", async (route) => {
      const url = new URL(route.request().url());
      const offset = Number(url.searchParams.get("offset") ?? "0");
      const pageRows = offset === 0 ? rows.slice(0, 5) : rows.slice(5);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(pageRows),
      });
    });

    await register(page, "pagesearch");
    const sidebar = page.getByRole("complementary").first();
    const dialog = page.getByRole("dialog", { name: "Search conversations" });
    const input = dialog.getByRole("textbox", { name: "Search conversations" });

    await sidebar.getByRole("button", { name: "Search conversations" }).click();
    await input.fill("star plan");

    // First page: exactly 5 rows.
    const list = dialog.locator("[data-conv-scroll]");
    await expect(list.locator("[data-search-row]")).toHaveCount(5);
    await expect(list.locator("[data-search-row]").first()).toContainText(
      "Star plan doc 0",
    );

    // Scroll to the bottom → the remaining 2 append.
    await list.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    await expect(list.locator("[data-search-row]")).toHaveCount(7);
    await expect(list.locator("[data-search-row]").last()).toContainText(
      "Star plan doc 6",
    );
  });
});
