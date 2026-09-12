import { expect, test, type Page } from "@playwright/test";

// Phase 8 Stage 7 (plan): the one AI flow this phase adds. Unlike every
// other E2E spec here, this one logs in as a MEMBER, not the founder —
// the whole point is to prove the permission filter (ADR-0014,
// retrieval_service._is_visible) holds end-to-end through a real
// browser session against the real backend, not just in the fake-client
// integration tests. Same prerequisites as the other specs: a running
// dev stack with E2E_TEST_MODE=true/NEXT_PUBLIC_E2E_TEST_MODE=true and
// `make seed` already run — plus a real OPENAI_API_KEY configured on the
// running backend, since this flow (unlike every other E2E spec) makes
// genuine calls to the AI provider.
const MEMBER_EMAIL = "developer@trinolit.com";

async function loginAsDeveloper(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/e2e test email/i).fill(MEMBER_EMAIL);
  await page.getByRole("button", { name: /e2e test sign in/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test("a MEMBER summarizes a meeting they attended, then the assistant admits it doesn't know about a project they aren't a member of", async ({
  page,
}) => {
  // Two real OpenAI round-trips in this one flow (summarize, then
  // embed+complete for the assistant) — well past Playwright's default
  // 30s test budget.
  test.setTimeout(90_000);
  await loginAsDeveloper(page);

  // "Sprint Retrospective" — developer@trinolit.com is its seeded
  // *creator* (scripts/seed.py), not just a participant: RBAC.md's own
  // "Meeting edit" rule is creator-or-MANAGER+, and a participant does
  // not gain edit rights merely by being invited, so this is the one
  // meeting a MEMBER can actually summarize.
  await page.goto("/meetings");
  await page.getByRole("link", { name: "Sprint Retrospective" }).click();
  await expect(page).toHaveURL(/\/meetings\/[^/]+$/);

  await page.getByRole("button", { name: "Notes" }).click();
  await page
    .getByRole("button", { name: /^summarize$|^regenerate summary$/i })
    .click();
  // A real OpenAI call is in flight — generous timeout, not the default 5s.
  await expect(page.getByText("Not summarized yet.")).not.toBeVisible({
    timeout: 30_000,
  });

  // Codex Stage 7 P1: this must probe the *project's own* content, not
  // one of its tasks — RBAC.md documents task read as org-wide with no
  // ownership-split at all (retrieval_service._is_visible's TASK branch
  // passes every task through unconditionally), so a task would have
  // been legitimately retrievable regardless of project membership,
  // proving nothing about project isolation. "Founder Ops" is a seeded
  // project with no member_emails at all (scripts/seed.py) — the
  // developer genuinely is not a project_members row on it, and its
  // *description* (unlike its tasks) is gated by ensure_project_visible,
  // so it must never reach the assistant's answer.
  await page.goto("/assistant");
  await page
    .getByLabel(/ask a question/i)
    .fill("What is the Founder Ops project working on?");
  await page.getByRole("button", { name: "Ask" }).click();

  const answer = page.locator("li").filter({ hasText: "Assistant" }).last();
  await expect(answer).toBeVisible({ timeout: 30_000 });
  await expect(answer).not.toContainText(/fundraising|investor|acquisition/i);
});
