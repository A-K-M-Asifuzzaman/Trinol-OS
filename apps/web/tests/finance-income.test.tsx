import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import IncomePage from "@/app/(app)/finance/income/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

const income = {
  id: "income-1",
  amount: "1500.00",
  currency: "USD",
  source: "Consulting retainer",
  client_id: null,
  project_id: null,
  invoice_id: null,
  received_on: "2026-01-01",
  payment_method: "bank_transfer",
  reference: null,
  notes: null,
  created_by: "01960000-0000-7000-8000-000000000002",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderIncomePage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <IncomePage />
    </QueryClientProvider>,
  );
}

describe("IncomePage", () => {
  it("shows the loading state before data arrives", () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/income`, () =>
        HttpResponse.json({ items: [income], total: 1 }),
      ),
    );
    renderIncomePage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the populated state once income loads", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/income`, () =>
        HttpResponse.json({ items: [income], total: 1 }),
      ),
    );
    renderIncomePage();
    await waitFor(() =>
      expect(screen.getByText("Consulting retainer")).toBeInTheDocument(),
    );
    expect(screen.getByText("USD 1500.00")).toBeInTheDocument();
  });

  it("shows the empty state when there is no income", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/income`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderIncomePage();
    await waitFor(() =>
      expect(screen.getByText(/no income recorded yet/i)).toBeInTheDocument(),
    );
  });

  it("shows the error state when the request fails", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/income`, () =>
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
    renderIncomePage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Missing required permission")).toBeInTheDocument();
  });

  it("shows the New income control", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/income`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderIncomePage();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New income" }),
      ).toBeInTheDocument(),
    );
  });
});
