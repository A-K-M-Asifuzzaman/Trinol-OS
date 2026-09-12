"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  cancelInvoice,
  fetchClient,
  fetchInvoice,
  fetchPayments,
  recordPayment,
  sendInvoice,
  type Invoice,
} from "@/lib/api/client";

const PAYABLE_STATUSES = new Set(["SENT", "PARTIALLY_PAID"]);
const CANCELLABLE_STATUSES = new Set(["DRAFT", "SENT", "PARTIALLY_PAID"]);

export default function InvoiceDetailPage() {
  const params = useParams<{ id: string }>();
  const invoiceId = params.id;
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);

  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["invoice", invoiceId],
    queryFn: () => fetchInvoice(invoiceId),
  });
  const client = useQuery({
    queryKey: ["client-for-invoice", data?.client_id],
    queryFn: () => fetchClient(data!.client_id),
    enabled: !!data?.client_id,
  });

  // No client-side permission pre-check — attempt the call, surface
  // whatever ApiError comes back, same pattern every other mutation in
  // this app already uses (e.g. meetings/[id]/page.tsx's handleDeleteMeeting).
  async function handleSend() {
    setActionError(null);
    setActionPending(true);
    try {
      await sendInvoice(invoiceId);
      queryClient.invalidateQueries({ queryKey: ["invoice", invoiceId] });
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not send this invoice.",
      );
    } finally {
      setActionPending(false);
    }
  }

  async function handleCancel() {
    setActionError(null);
    setActionPending(true);
    try {
      await cancelInvoice(invoiceId);
      queryClient.invalidateQueries({ queryKey: ["invoice", invoiceId] });
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Could not cancel this invoice.",
      );
    } finally {
      setActionPending(false);
    }
  }

  if (isLoading) return <ListLoadingState />;
  if (error || !data) {
    return (
      <ListErrorState
        message={
          error instanceof ApiError
            ? error.message
            : "Something went wrong loading this invoice."
        }
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold">{data.invoice_number}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {client.data?.name ?? data.client_id}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge>{data.is_overdue ? "OVERDUE" : data.status}</Badge>
          <a
            href={`/api/v1/finance/invoices/${invoiceId}/pdf`}
            className="inline-flex h-9 items-center justify-center rounded border border-border bg-transparent px-4 text-sm font-medium hover:bg-muted"
          >
            Download PDF
          </a>
          {data.status === "DRAFT" ? (
            <Button onClick={handleSend} disabled={actionPending}>
              Send
            </Button>
          ) : null}
          {CANCELLABLE_STATUSES.has(data.status) ? (
            <Button
              variant="outline"
              onClick={handleCancel}
              disabled={actionPending}
            >
              Cancel invoice
            </Button>
          ) : null}
        </div>
      </div>
      {actionError ? (
        <p role="alert" className="text-sm text-destructive">
          {actionError}
        </p>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded border border-border p-4 text-sm">
          <p>
            <span className="text-muted-foreground">Issue date:</span>{" "}
            {data.issue_date}
          </p>
          <p>
            <span className="text-muted-foreground">Due date:</span>{" "}
            {data.due_date}
          </p>
          {data.notes ? (
            <p className="mt-2 whitespace-pre-wrap">{data.notes}</p>
          ) : null}
        </div>
        <InvoiceTotals invoice={data} />
      </div>

      <LineItemsTable invoice={data} />

      <PaymentsSection invoiceId={invoiceId} invoice={data} />
    </div>
  );
}

function InvoiceTotals({ invoice }: { invoice: Invoice }) {
  return (
    <div className="rounded border border-border p-4 text-sm">
      <Row label="Subtotal" value={`${invoice.currency} ${invoice.subtotal}`} />
      <Row
        label="Discount"
        value={`-${invoice.currency} ${invoice.discount_amount}`}
      />
      <Row label="Tax" value={`${invoice.currency} ${invoice.tax_amount}`} />
      <Row
        label="Total"
        value={`${invoice.currency} ${invoice.total}`}
        strong
      />
      <Row label="Paid" value={`${invoice.currency} ${invoice.amount_paid}`} />
    </div>
  );
}

function Row({
  label,
  value,
  strong,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div
      className={`flex justify-between py-0.5 ${strong ? "border-t border-border pt-1.5 font-semibold" : ""}`}
    >
      <span className="text-muted-foreground">{label}</span>
      <span>{value}</span>
    </div>
  );
}

function LineItemsTable({ invoice }: { invoice: Invoice }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Description</th>
            <th className="py-2 font-medium">Qty</th>
            <th className="py-2 font-medium">Unit price</th>
            <th className="py-2 font-medium">Line total</th>
          </tr>
        </thead>
        <tbody>
          {invoice.items.map((item) => (
            <tr key={item.id} className="border-b border-border">
              <td className="py-2">{item.description}</td>
              <td className="py-2">{item.quantity}</td>
              <td className="py-2">
                {invoice.currency} {item.unit_price}
              </td>
              <td className="py-2">
                {invoice.currency} {item.line_total}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PaymentsSection({
  invoiceId,
  invoice,
}: {
  invoiceId: string;
  invoice: Invoice;
}) {
  const queryClient = useQueryClient();
  const [amount, setAmount] = useState("");
  const [paidOn, setPaidOn] = useState("");
  const [method, setMethod] = useState("");
  const [rowError, setRowError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const payments = useQuery({
    queryKey: ["payments", invoiceId],
    queryFn: () => fetchPayments(invoiceId),
  });

  async function handleRecord(e: FormEvent) {
    e.preventDefault();
    setRowError(null);
    setSubmitting(true);
    try {
      await recordPayment(invoiceId, {
        amount,
        currency: invoice.currency,
        paid_on: paidOn,
        method,
      });
      setAmount("");
      setPaidOn("");
      setMethod("");
      queryClient.invalidateQueries({ queryKey: ["payments", invoiceId] });
      queryClient.invalidateQueries({ queryKey: ["invoice", invoiceId] });
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not record that payment.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">Payments</h2>
      {PAYABLE_STATUSES.has(invoice.status) ? (
        <form
          onSubmit={handleRecord}
          className="flex flex-wrap items-end gap-2"
        >
          <div>
            <label htmlFor="payment-amount" className="text-sm font-medium">
              Amount
            </label>
            <input
              id="payment-amount"
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="mt-1 rounded border border-border px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label htmlFor="payment-paid-on" className="text-sm font-medium">
              Date
            </label>
            <input
              id="payment-paid-on"
              type="date"
              required
              value={paidOn}
              onChange={(e) => setPaidOn(e.target.value)}
              className="mt-1 rounded border border-border px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label htmlFor="payment-method" className="text-sm font-medium">
              Method
            </label>
            <input
              id="payment-method"
              required
              value={method}
              onChange={(e) => setMethod(e.target.value)}
              className="mt-1 rounded border border-border px-3 py-1.5 text-sm"
            />
          </div>
          <Button type="submit" disabled={submitting}>
            Record payment
          </Button>
        </form>
      ) : null}
      {rowError ? (
        <p role="alert" className="text-sm text-destructive">
          {rowError}
        </p>
      ) : null}
      {payments.isLoading ? (
        <ListLoadingState />
      ) : payments.error || !payments.data ? (
        <ListErrorState message="Something went wrong loading payments." />
      ) : payments.data.items.length === 0 ? (
        <ListEmptyState title="No payments recorded yet" />
      ) : (
        <ul className="space-y-2">
          {payments.data.items.map((payment) => (
            <li
              key={payment.id}
              className="flex items-center justify-between rounded border border-border p-3 text-sm"
            >
              <span>
                {payment.paid_on} &middot; {payment.method}
              </span>
              <span className="font-medium">
                {payment.currency} {payment.amount}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
