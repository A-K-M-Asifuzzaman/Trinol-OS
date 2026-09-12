"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  createInvoice,
  fetchClients,
  fetchInvoices,
  type Invoice,
} from "@/lib/api/client";

type LineItemDraft = {
  description: string;
  quantity: string;
  unitPrice: string;
};

const EMPTY_ITEM: LineItemDraft = {
  description: "",
  quantity: "1",
  unitPrice: "",
};

// Same client-rendered/four-state pattern as Leads/Income. No edit UI for
// a DRAFT invoice's own fields this stage (ponytail — the plan's exit
// criteria only asks for create/send/cancel/pay, not an edit form); the
// backend's own PATCH still exists for a later stage to build a UI for.
export default function InvoicesPage() {
  const queryClient = useQueryClient();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["invoices"],
    queryFn: () => fetchInvoices({ limit: 50, offset: 0 }),
  });
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Invoices</h1>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "New invoice"}
        </Button>
      </div>
      {showForm ? (
        <CreateInvoiceForm
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["invoices"] });
          }}
        />
      ) : null}
      {isLoading ? (
        <ListLoadingState />
      ) : error ? (
        <ListErrorState
          message={
            error instanceof ApiError
              ? error.message
              : "Something went wrong loading invoices."
          }
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <ListEmptyState
          title="No invoices yet"
          description="Create one to get started."
        />
      ) : (
        <InvoiceTable invoices={data.items} />
      )}
    </div>
  );
}

function CreateInvoiceForm({ onCreated }: { onCreated: () => void }) {
  const clients = useQuery({
    queryKey: ["clients-for-invoice"],
    queryFn: () => fetchClients({ limit: 200 }),
  });
  const [clientId, setClientId] = useState("");
  const [issueDate, setIssueDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [items, setItems] = useState<LineItemDraft[]>([{ ...EMPTY_ITEM }]);
  const [discountAmount, setDiscountAmount] = useState("0");
  const [taxAmount, setTaxAmount] = useState("0");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function updateItem(index: number, patch: Partial<LineItemDraft>) {
    setItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
  }

  function addItem() {
    setItems((prev) => [...prev, { ...EMPTY_ITEM }]);
  }

  function removeItem(index: number) {
    setItems((prev) => prev.filter((_, i) => i !== index));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!clientId) {
      setFormError("Select a client.");
      return;
    }
    setSubmitting(true);
    try {
      await createInvoice({
        client_id: clientId,
        issue_date: issueDate,
        due_date: dueDate,
        currency: "USD",
        items: items.map((item) => ({
          description: item.description,
          quantity: item.quantity,
          unit_price: item.unitPrice,
        })),
        discount_amount: discountAmount || "0",
        tax_amount: taxAmount || "0",
      });
      onCreated();
    } catch (err) {
      setFormError(
        err instanceof ApiError
          ? err.message
          : "Could not create that invoice.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-3 rounded border border-border p-4"
      noValidate
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor="invoice-client" className="text-sm font-medium">
            Client
          </label>
          <select
            id="invoice-client"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          >
            <option value="">Select...</option>
            {clients.data?.items.map((client) => (
              <option key={client.id} value={client.id}>
                {client.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="invoice-issue-date" className="text-sm font-medium">
            Issue date
          </label>
          <input
            id="invoice-issue-date"
            type="date"
            required
            value={issueDate}
            onChange={(e) => setIssueDate(e.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label htmlFor="invoice-due-date" className="text-sm font-medium">
            Due date
          </label>
          <input
            id="invoice-due-date"
            type="date"
            required
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          />
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-sm font-medium">Line items</p>
        {items.map((item, index) => (
          <div key={index} className="flex flex-wrap items-end gap-2">
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">
                Description
              </label>
              <input
                required
                value={item.description}
                onChange={(e) =>
                  updateItem(index, { description: e.target.value })
                }
                className="mt-1 w-full rounded border border-border px-3 py-1.5 text-sm"
              />
            </div>
            <div className="w-24">
              <label className="text-xs text-muted-foreground">Qty</label>
              <input
                required
                value={item.quantity}
                onChange={(e) =>
                  updateItem(index, { quantity: e.target.value })
                }
                className="mt-1 w-full rounded border border-border px-3 py-1.5 text-sm"
              />
            </div>
            <div className="w-28">
              <label className="text-xs text-muted-foreground">
                Unit price
              </label>
              <input
                required
                value={item.unitPrice}
                onChange={(e) =>
                  updateItem(index, { unitPrice: e.target.value })
                }
                className="mt-1 w-full rounded border border-border px-3 py-1.5 text-sm"
              />
            </div>
            {items.length > 1 ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => removeItem(index)}
              >
                Remove
              </Button>
            ) : null}
          </div>
        ))}
        <Button type="button" variant="outline" onClick={addItem}>
          Add line item
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="invoice-discount" className="text-sm font-medium">
            Discount
          </label>
          <input
            id="invoice-discount"
            value={discountAmount}
            onChange={(e) => setDiscountAmount(e.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label htmlFor="invoice-tax" className="text-sm font-medium">
            Tax
          </label>
          <input
            id="invoice-tax"
            value={taxAmount}
            onChange={(e) => setTaxAmount(e.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          />
        </div>
      </div>

      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <Button type="submit" disabled={submitting}>
        {submitting ? "Creating..." : "Create invoice"}
      </Button>
    </form>
  );
}

function InvoiceTable({ invoices }: { invoices: Invoice[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Invoice</th>
            <th className="py-2 font-medium">Status</th>
            <th className="py-2 font-medium">Due date</th>
            <th className="py-2 font-medium">Total</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((invoice) => (
            <tr key={invoice.id} className="border-b border-border">
              <td className="py-2">
                <Link
                  href={`/invoices/${invoice.id}`}
                  className="font-medium hover:underline"
                >
                  {invoice.invoice_number}
                </Link>
              </td>
              <td className="py-2">
                <Badge>{invoice.is_overdue ? "OVERDUE" : invoice.status}</Badge>
              </td>
              <td className="py-2">{invoice.due_date}</td>
              <td className="py-2">
                {invoice.currency} {invoice.total}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
