import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import InvoiceDetailPage from "@/app/(app)/invoices/[id]/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "invoice-1" }),
}));

const draftInvoice = {
  id: "invoice-1",
  invoice_number: "TRI-2026-0001",
  client_id: "client-1",
  project_id: null,
  issue_date: "2026-01-01",
  due_date: "2026-01-15",
  currency: "USD",
  items: [
    {
      id: "item-1",
      description: "Consulting",
      quantity: "1",
      unit_price: "1000.00",
      line_total: "1000.00",
      position: 0,
    },
  ],
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

const client = {
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
};

function renderInvoiceDetailPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <InvoiceDetailPage />
    </QueryClientProvider>,
  );
}

function stubInvoice(invoice: typeof draftInvoice) {
  server.use(
    http.get(`${APP_ORIGIN}/api/v1/finance/invoices/invoice-1`, () =>
      HttpResponse.json(invoice),
    ),
    http.get(`${APP_ORIGIN}/api/v1/clients/client-1`, () =>
      HttpResponse.json(client),
    ),
    http.get(`${APP_ORIGIN}/api/v1/finance/invoices/invoice-1/payments`, () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
  );
}

describe("InvoiceDetailPage", () => {
  it("shows the loading state before data arrives", () => {
    stubInvoice(draftInvoice);
    renderInvoiceDetailPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows invoice details, line items, and a Send button for a DRAFT invoice", async () => {
    stubInvoice(draftInvoice);
    renderInvoiceDetailPage();
    await waitFor(() =>
      expect(screen.getByText("TRI-2026-0001")).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByText("Acme Corp")).toBeInTheDocument(),
    );
    expect(screen.getByText("Consulting")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      "/api/v1/finance/invoices/invoice-1/pdf",
    );
  });

  it("hides Send and shows the payment form for a SENT invoice", async () => {
    stubInvoice({ ...draftInvoice, status: "SENT" });
    renderInvoiceDetailPage();
    await waitFor(() =>
      expect(screen.getByText("TRI-2026-0001")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "Send" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Record payment" }),
    ).toBeInTheDocument();
  });

  it("hides Cancel invoice for a PAID invoice", async () => {
    stubInvoice({ ...draftInvoice, status: "PAID", amount_paid: "1000.00" });
    renderInvoiceDetailPage();
    await waitFor(() =>
      expect(screen.getByText("TRI-2026-0001")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "Cancel invoice" }),
    ).not.toBeInTheDocument();
  });

  it("sends the invoice when Send is clicked", async () => {
    stubInvoice(draftInvoice);
    let sendCalled = false;
    server.use(
      http.post(`${APP_ORIGIN}/api/v1/finance/invoices/invoice-1/send`, () => {
        sendCalled = true;
        return HttpResponse.json({ ...draftInvoice, status: "SENT" });
      }),
    );
    renderInvoiceDetailPage();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sendCalled).toBe(true));
  });

  it("shows an error message when the invoice fails to load", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/finance/invoices/invoice-1`, () =>
        HttpResponse.json(
          {
            error: {
              code: "NOT_FOUND",
              message: "Invoice not found",
              request_id: null,
              details: {},
            },
          },
          { status: 404 },
        ),
      ),
    );
    renderInvoiceDetailPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Invoice not found")).toBeInTheDocument();
  });
});
