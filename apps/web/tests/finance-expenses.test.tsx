import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import ExpensesPage from "@/app/(app)/finance/expenses/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

const expense = {
  id: "expense-1",
  amount: "49.99",
  currency: "USD",
  category: "SOFTWARE",
  description: "Design tool subscription",
  vendor: null,
  spent_on: "2026-01-01",
  payment_method: "card",
  receipt_file_id: null,
  notes: null,
  created_by: "01960000-0000-7000-8000-000000000002",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderExpensesPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ExpensesPage />
    </QueryClientProvider>,
  );
}

describe("ExpensesPage", () => {
  it("shows the loading state before data arrives", () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/expenses`, () =>
        HttpResponse.json({ items: [expense], total: 1 }),
      ),
    );
    renderExpensesPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the populated state once expenses load, with an Upload control", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/expenses`, () =>
        HttpResponse.json({ items: [expense], total: 1 }),
      ),
    );
    renderExpensesPage();
    await waitFor(() =>
      expect(screen.getByText("Design tool subscription")).toBeInTheDocument(),
    );
    expect(screen.getByText("SOFTWARE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeInTheDocument();
  });

  it("shows a View link instead of Upload once a receipt exists", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/expenses`, () =>
        HttpResponse.json({
          items: [{ ...expense, receipt_file_id: "file-1" }],
          total: 1,
        }),
      ),
    );
    renderExpensesPage();
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "View" })).toHaveAttribute(
        "href",
        "/api/v1/finance/expenses/expense-1/receipt",
      ),
    );
  });

  it("shows the empty state when there are no expenses", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/expenses`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderExpensesPage();
    await waitFor(() =>
      expect(screen.getByText(/no expenses recorded yet/i)).toBeInTheDocument(),
    );
  });

  it("shows the error state when the request fails", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/expenses`, () =>
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
    renderExpensesPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });
});
