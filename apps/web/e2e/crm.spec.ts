import { expect, test, type Page } from "@playwright/test";

// TESTING.md §5 / MASTER_PROMPT §37: three of the eight E2E flows —
// create lead, convert lead, create client — added in their own file
// rather than smoke.spec.ts's single test (Phase 2's whole E2E
// foundation): CRM is a distinct chapter, and smoke.spec.ts's own
// docstring already flags "or a sibling crm.spec.ts if the single-spec-
// file convention gets unwieldy" as the acceptable split point. Same
// prerequisites as smoke.spec.ts: a running dev stack with
// E2E_TEST_MODE=true/NEXT_PUBLIC_E2E_TEST_MODE=true and `make seed`
// already run, so `founder@trinolit.com` exists to log in as.
const SEEDED_EMAIL = "founder@trinolit.com";

async function loginAsFounder(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/e2e test email/i).fill(SEEDED_EMAIL);
  await page.getByRole("button", { name: /e2e test sign in/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test("login, create a lead, and convert it to a client + project", async ({
  page,
}) => {
  await loginAsFounder(page);

  const unique = Date.now().toString();
  const leadName = `Playwright Lead ${unique}`;

  await page.goto("/leads");
  await page.getByRole("button", { name: /new lead/i }).click();
  await page.getByLabel(/^name$/i).fill(leadName);
  await page.getByLabel(/^email$/i).fill(`lead-${unique}@example.test`);
  await page.getByRole("button", { name: /^create lead$/i }).click();
  const leadLink = page.getByRole("link", { name: leadName });
  await expect(leadLink).toBeVisible();

  await leadLink.click();
  await expect(page).toHaveURL(/\/leads\/[^/]+$/);

  // Converting redirects straight to the new project (ROADMAP.md Phase 3
  // exit criteria) — the natural next stop, and proof the conversion
  // actually created a client + project, not just flipped the lead's
  // stage.
  await page.getByRole("button", { name: /convert to client/i }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+$/);
  await expect(page.getByRole("heading", { name: leadName })).toBeVisible();
});

test("login and create a client directly", async ({ page }) => {
  await loginAsFounder(page);

  const unique = Date.now().toString();
  const clientName = `Playwright Client ${unique}`;

  await page.goto("/clients");
  await page.getByRole("button", { name: /new client/i }).click();
  await page.getByLabel(/^name$/i).fill(clientName);
  await page.getByRole("button", { name: /^create client$/i }).click();
  await expect(page.getByRole("link", { name: clientName })).toBeVisible();
});
