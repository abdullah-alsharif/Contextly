import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // Generous budget: each run boots a fresh dev server that compiles routes
  // on first hit, and the smoke flow polls backend ingestion (slow machines).
  timeout: 240_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 1,
  globalSetup: "./e2e/global-setup.mjs",
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    // Always start a fresh dev server: the compose `frontend` container on
    // :3000 serves a stale build and must not be reused for tests.
    reuseExistingServer: false,
    timeout: 120_000,
  },
});