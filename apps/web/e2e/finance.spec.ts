import { expect, test, type Page } from "@playwright/test";

// MASTER_PROMPT §37's one Finance flow: create an invoice with line items
// and confirm the SERVER-computed total actually reflects ADR-0007's
// ROUND_HALF_UP-to-2-decimals rule — the expected total is derived here
// from the same raw quantity/price inputs the form is filled with, not
// hardcoded, so a broken rounding implementation would fail this
// assertion rather than just not matching a frozen snapshot string. Same
// prerequisites as every other e2e/*.spec.ts file: a running dev stack
// with E2E_TEST_MODE=true/NEXT_PUBLIC_E2E_TEST_MODE=true and `make seed`
// already run (this test picks the seeded "Acme Corp" client).
const SEEDED_EMAIL = "founder@trinolit.com";

async function loginAsFounder(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/e2e test email/i).fill(SEEDED_EMAIL);
  await page.getByRole("button", { name: /e2e test sign in/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

function isoDate(daysFromNow: number): string {
  const d = new Date();
  d.setDate(d.getDate() + daysFromNow);
  return d.toISOString().slice(0, 10);
}

// ADR-0007: line_total = round(quantity * unit_price, 2), ROUND_HALF_UP.
// Math.round is round-half-away-from-zero for these positive inputs,
// the same behavior for every value used below.
function lineTotal(quantity: number, unitPrice: number): number {
  return Math.round((quantity * unitPrice + Number.EPSILON) * 100) / 100;
}

test("create an invoice with line items and see the server-computed total", async ({
  page,
}) => {
  await loginAsFounder(page);

  const item1 = {
    description: "Website redesign",
    quantity: 3,
    unitPrice: 33.33,
  };
  // Deliberately needs real rounding, not just formatting: 1.111 * 3.33 =
  // 3.69963, which only rounds to a clean "3.70" under ROUND_HALF_UP.
  const item2 = {
    description: "Hosting setup",
    quantity: 1.111,
    unitPrice: 3.33,
  };
  const discount = 2.0;
  const tax = 1.5;
  const item1Total = lineTotal(item1.quantity, item1.unitPrice);
  const item2Total = lineTotal(item2.quantity, item2.unitPrice);
  const subtotal = item1Total + item2Total;
  const expectedTotal = (subtotal - discount + tax).toFixed(2);

  await page.goto("/invoices");
  await page.getByRole("button", { name: /new invoice/i }).click();

  await page.getByLabel(/^client$/i).selectOption({ label: "Acme Corp" });
  await page.getByLabel(/issue date/i).fill(isoDate(0));
  await page.getByLabel(/due date/i).fill(isoDate(14));

  // The description/qty/unit-price inputs have no htmlFor-linked <label>
  // (invoices/page.tsx's own CreateInvoiceForm), so they're located
  // structurally by their row container instead of getByLabel.
  const rows = page.locator("form div.flex.flex-wrap.items-end.gap-2");
  await rows.nth(0).locator("input").nth(0).fill(item1.description);
  await rows.nth(0).locator("input").nth(1).fill(String(item1.quantity));
  await rows.nth(0).locator("input").nth(2).fill(String(item1.unitPrice));

  await page.getByRole("button", { name: /add line item/i }).click();
  await rows.nth(1).locator("input").nth(0).fill(item2.description);
  await rows.nth(1).locator("input").nth(1).fill(String(item2.quantity));
  await rows.nth(1).locator("input").nth(2).fill(String(item2.unitPrice));

  await page.getByLabel(/^discount$/i).fill(discount.toFixed(2));
  await page.getByLabel(/^tax$/i).fill(tax.toFixed(2));

  // Six invoices are already seeded (scripts/seed.py), so picking "the new
  // one" off the list by sort order or link text is unreliable — read the
  // real id straight from the creation response instead.
  const [response] = await Promise.all([
    page.waitForResponse(
      (res) =>
        res.request().method() === "POST" &&
        res.url().endsWith("/api/v1/finance/invoices") &&
        res.ok(),
    ),
    page.getByRole("button", { name: /^create invoice$/i }).click(),
  ]);
  const created = (await response.json()) as { id: string };

  await page.goto(`/invoices/${created.id}`);
  await expect(page).toHaveURL(/\/invoices\/[^/]+$/);

  await expect(page.getByText(`USD ${item2Total.toFixed(2)}`)).toBeVisible();
  await expect(page.getByText(`USD ${expectedTotal}`)).toBeVisible();
});
