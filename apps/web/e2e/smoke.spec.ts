import { expect, test } from "@playwright/test";

// TESTING.md §5: the smallest slice of the eight spec flows worth driving
// end to end — login, create project, create task, move task on the
// board. Needs a running dev stack with `E2E_TEST_MODE=true`/
// `NEXT_PUBLIC_E2E_TEST_MODE=true` set (see .env.example) and `make seed`
// already run, so `founder@trinolit.com` exists to log in as.
const SEEDED_EMAIL = "founder@trinolit.com";

test("login, create a project, create a task, and move it on the board", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel(/e2e test email/i).fill(SEEDED_EMAIL);
  await page.getByRole("button", { name: /e2e test sign in/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  const unique = Date.now().toString();
  const projectCode = `E2E${unique}`;
  const projectName = `Playwright Smoke ${unique}`;

  await page.goto("/projects");
  await page.getByRole("button", { name: /new project/i }).click();
  await page.getByLabel(/project code/i).fill(projectCode);
  await page.getByLabel(/^name$/i).fill(projectName);
  await page.getByRole("button", { name: /^create project$/i }).click();
  const projectLink = page.getByRole("link", { name: projectName });
  await expect(projectLink).toBeVisible();

  const taskTitle = `Playwright smoke task ${unique}`;
  await page.goto("/tasks");
  await page.getByRole("button", { name: /new task/i }).click();
  await page.getByLabel(/^title$/i).fill(taskTitle);
  await page.getByLabel(/project/i).selectOption({ label: projectName });
  await page.getByRole("button", { name: /^create task$/i }).click();
  await expect(page.getByRole("link", { name: taskTitle })).toBeVisible();

  await page.goto("/projects");
  await projectLink.click();
  await expect(page).toHaveURL(/\/projects\/[^/]+$/);

  const todoColumn = page.getByTestId("board-column-TODO");
  const doneColumn = page.getByTestId("board-column-DONE");
  const taskCard = page.locator('[data-testid^="board-task-"]', {
    hasText: taskTitle,
  });
  await expect(taskCard).toBeVisible();
  await expect(todoColumn.getByText(taskTitle)).toBeVisible();

  await taskCard.dragTo(doneColumn);
  await expect(doneColumn.getByText(taskTitle)).toBeVisible();
});
