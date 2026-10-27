import { defineConfig, devices } from "@playwright/test";

// Browser smoke test (e2e/) of a running stack, not of `next dev`. The Compose service `e2e` runs
// it inside Caddy's network namespace, so the browser opens http://localhost and keeps the API's
// Secure cookies (they are dropped over plain http on any other name).
export default defineConfig({
  testDir: "e2e",
  timeout: 15 * 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list", { printSteps: true }], ["html", { open: "never" }]],
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost",
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
