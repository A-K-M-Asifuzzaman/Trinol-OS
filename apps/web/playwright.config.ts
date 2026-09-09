import { defineConfig, devices } from "@playwright/test";

// TESTING.md §5: "Playwright, Chromium, against the docker-compose stack
// with seeded data." No `webServer` here on purpose — this runs against a
// stack the caller already has up (`make dev` + `make seed`, or CI's own
// future job), not one Playwright starts and tears down itself. Runs on
// main/release-candidate branches, not every PR (§6) — nothing in ci.yml
// changes for this.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
