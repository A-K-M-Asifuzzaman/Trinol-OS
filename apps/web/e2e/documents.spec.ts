import { expect, test, type Page } from "@playwright/test";

// Phase 6 plan decision 7: one flow added beyond MASTER_PROMPT §37's fixed
// eight (which names nothing for Documents), same precedent
// meetings.spec.ts already set — one flow per major new capability. Same
// prerequisites as every other e2e/*.spec.ts file: a running dev stack with
// E2E_TEST_MODE=true/NEXT_PUBLIC_E2E_TEST_MODE=true and `make seed` already
// run, so `founder@trinolit.com` and the "TrinolIT Website" project exist.
const SEEDED_EMAIL = "founder@trinolit.com";
const SEEDED_PROJECT_NAME = "TrinolIT Website";

async function loginAsFounder(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/e2e test email/i).fill(SEEDED_EMAIL);
  await page.getByRole("button", { name: /e2e test sign in/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test("create a document reference linked to a project", async ({ page }) => {
  await loginAsFounder(page);

  const unique = Date.now().toString();
  const title = `Playwright Document ${unique}`;

  await page.goto("/documents");
  await page.getByRole("button", { name: "New document" }).click();
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("URL").fill("https://github.com/trinolit/trinol-os");
  await page.getByLabel("Kind").selectOption("GITHUB");
  await page.getByLabel("Link to").selectOption("project");
  await page.getByLabel("Project").selectOption({ label: SEEDED_PROJECT_NAME });
  await page.getByRole("button", { name: "Create document" }).click();

  // Not just "a row appears" — assert the real thing: the correct title,
  // the correct kind badge, and the correct linked-project name, the same
  // "assert the real thing" discipline finance.spec.ts's own rounding
  // check established for this phase's own E2E flow.
  const row = page.getByRole("row", { name: new RegExp(title) });
  await expect(row).toBeVisible();
  await expect(row.getByText("GitHub")).toBeVisible();
  await expect(row.getByText(SEEDED_PROJECT_NAME)).toBeVisible();

  const link = row.getByRole("link", { name: title });
  await expect(link).toHaveAttribute(
    "href",
    "https://github.com/trinolit/trinol-os",
  );
  await expect(link).toHaveAttribute("target", "_blank");
});
