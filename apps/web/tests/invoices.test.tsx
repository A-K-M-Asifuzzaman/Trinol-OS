import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import InvoicesPage from "@/app/(app)/invoices/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

const invoice = {
  id: "invoice-1",
  invoice_number: "TRI-2026-0001",
  client_id: "client-1",
  project_id: null,
  issue_date: "2026-01-01",
  due_date: "2026-01-15",
  currency: "USD",
  items: [],
  subtotal: "1000.00",
  discount_amount: "0",
  tax_amount: "0",
  total: "1000.00",
  amount_paid: "0",
  status: "DRAFT",
  is_overdue: false,
  notes: null,
  terms: null,
  sent_at: null,
  created_by: "01960000-0000-7000-8000-000000000002",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderInvoicesPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <InvoicesPage />
    </QueryClientProvider>,
  );
}

describe("InvoicesPage", () => {
  it("shows the loading state before data arrives", () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/invoices`, () =>
        HttpResponse.json({ items: [invoice], total: 1 }),
      ),
    );
    renderInvoicesPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the populated state once invoices load", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/invoices`, () =>
        HttpResponse.json({ items: [invoice], total: 1 }),
      ),
    );
    renderInvoicesPage();
    await waitFor(() =>
      expect(screen.getByText("TRI-2026-0001")).toBeInTheDocument(),
    );
    expect(screen.getByText("DRAFT")).toBeInTheDocument();
  });

  it("shows OVERDUE instead of the stored status when is_overdue is true", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/invoices`, () =>
        HttpResponse.json({
          items: [{ ...invoice, status: "SENT", is_overdue: true }],
          total: 1,
        }),
      ),
    );
    renderInvoicesPage();
    await waitFor(() =>
      expect(screen.getByText("OVERDUE")).toBeInTheDocument(),
    );
  });

  it("shows the empty state when there are no invoices", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/invoices`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderInvoicesPage();
    await waitFor(() =>
      expect(screen.getByText(/no invoices yet/i)).toBeInTheDocument(),
    );
  });

  it("shows the error state when the request fails", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/invoices`, () =>
        HttpResponse.json(
          {
            error: {
              code: "FORBIDDEN",
              message: "Missing required permission",
              request_id: null,
              details: {},
            },
          },
          { status: 403 },
        ),
      ),
    );
    renderInvoicesPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });

  it("shows the create-invoice form with a client picker", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/invoices`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
      http.get(`${APP_ORIGIN}/api/v1/clients`, () =>
        HttpResponse.json({
          items: [
            {
              id: "client-1",
              name: "Acme Corp",
              company: null,
              email: null,
              phone: null,
              website: null,
              address: null,
              notes: null,
              status: "ACTIVE",
              owner_id: null,
              archived_at: null,
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        }),
      ),
    );
    renderInvoicesPage();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New invoice" }),
      ).toBeInTheDocument(),
    );
    screen.getByRole("button", { name: "New invoice" }).click();
    await waitFor(() =>
      expect(screen.getByText("Acme Corp")).toBeInTheDocument(),
    );
  });
});
