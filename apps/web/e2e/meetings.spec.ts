import { expect, test, type Page } from "@playwright/test";

// TESTING.md §5 / MASTER_PROMPT §37: one flow covering this phase's whole
// story — meeting -> attendee -> decision -> action item -> promote ->
// the resulting task is real, mirroring the granularity crm.spec.ts's own
// docstring already establishes (one flow per major capability, not per
// CRUD verb). Same prerequisites as smoke.spec.ts/crm.spec.ts: a running
// dev stack with E2E_TEST_MODE=true/NEXT_PUBLIC_E2E_TEST_MODE=true and
// `make seed` already run, so `founder@trinolit.com` exists to log in as.
const SEEDED_EMAIL = "founder@trinolit.com";

async function loginAsFounder(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/e2e test email/i).fill(SEEDED_EMAIL);
  await page.getByRole("button", { name: /e2e test sign in/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test("create a meeting, add an attendee, record a decision, add an action item, and promote it to a task", async ({
  page,
}) => {
  await loginAsFounder(page);

  const unique = Date.now().toString();
  const meetingTitle = `Playwright Meeting ${unique}`;

  await page.goto("/meetings");
  await page.getByRole("button", { name: /new meeting/i }).click();
  await page.getByLabel(/^title$/i).fill(meetingTitle);
  await page.locator("#starts_at").fill("2026-11-01T10:00");
  await page.locator("#ends_at").fill("2026-11-01T11:00");
  await page.getByRole("button", { name: /^create meeting$/i }).click();
  const meetingLink = page.getByRole("link", { name: meetingTitle });
  await expect(meetingLink).toBeVisible();

  await meetingLink.click();
  await expect(page).toHaveURL(/\/meetings\/[^/]+$/);

  await page.getByRole("button", { name: "Attendees" }).click();
  await page.getByLabel("Invite").selectOption("external");
  await page.getByLabel("Email").fill(`attendee-${unique}@example.test`);
  await page.getByRole("button", { name: /add attendee/i }).click();
  await expect(page.getByText(`attendee-${unique}@example.test`)).toBeVisible();

  const decisionBody = `Playwright decision ${unique}`;
  await page.getByRole("button", { name: "Decisions" }).click();
  await page.getByLabel(/new decision/i).fill(decisionBody);
  await page.getByRole("button", { name: /record decision/i }).click();
  await expect(page.getByText(decisionBody)).toBeVisible();

  const actionDescription = `Playwright action item ${unique}`;
  await page.getByRole("button", { name: "Action Items" }).click();
  await page.getByLabel(/new action item/i).fill(actionDescription);
  await page.getByRole("button", { name: /add action item/i }).click();
  await expect(page.getByText(actionDescription)).toBeVisible();

  await page.getByRole("button", { name: /promote to task/i }).click();
  const viewTaskLink = page.getByRole("link", { name: /view task/i });
  await expect(viewTaskLink).toBeVisible();

  // The promoted action really is a task, reachable from /tasks — not
  // just a link that happens to render (ROADMAP.md Phase 4 Stage 5 exit
  // criterion).
  await viewTaskLink.click();
  await expect(page).toHaveURL(/\/tasks\/[^/]+$/);
  await expect(
    page.getByRole("heading", { name: actionDescription }),
  ).toBeVisible();
});
