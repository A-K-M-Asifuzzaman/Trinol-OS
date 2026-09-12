"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  createIncome,
  deleteIncome,
  fetchIncome,
  type Income,
} from "@/lib/api/client";

// Same client-rendered/four-state pattern as Leads/Meetings. No edit UI
// this stage (ponytail — same scope decision Meetings' own frontend made
// for its sub-resources): create and delete cover the plan's exit
// criteria; add an edit form when requested.
export default function IncomePage() {
  const queryClient = useQueryClient();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["income"],
    queryFn: () => fetchIncome({ limit: 50, offset: 0 }),
  });
  const [showForm, setShowForm] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);

  async function handleDelete(incomeId: string) {
    setRowError(null);
    try {
      await deleteIncome(incomeId);
      queryClient.invalidateQueries({ queryKey: ["income"] });
    } catch (err) {
      setRowError(
        err instanceof ApiError ? err.message : "Could not delete that row.",
      );
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Income</h1>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "New income"}
        </Button>
      </div>
      {showForm ? (
        <CreateIncomeForm
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["income"] });
          }}
        />
      ) : null}
      {rowError ? (
        <p role="alert" className="text-sm text-destructive">
          {rowError}
        </p>
      ) : null}
      {isLoading ? (
        <ListLoadingState />
      ) : error ? (
        <ListErrorState
          message={
            error instanceof ApiError
              ? error.message
              : "Something went wrong loading income."
          }
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <ListEmptyState
          title="No income recorded yet"
          description="Record one to get started."
        />
      ) : (
        <IncomeTable items={data.items} onDelete={handleDelete} />
      )}
    </div>
  );
}

const createIncomeSchema = z.object({
  amount: z.string().regex(/^\d+(\.\d{1,2})?$/, "Enter a valid amount"),
  source: z.string().min(1, "Source is required"),
  receivedOn: z.string().min(1, "Date is required"),
  paymentMethod: z.string().min(1, "Payment method is required"),
});
type CreateIncomeValues = z.infer<typeof createIncomeSchema>;

function CreateIncomeForm({ onCreated }: { onCreated: () => void }) {
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateIncomeValues>({
    resolver: zodResolver(createIncomeSchema),
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    setSubmitting(true);
    try {
      await createIncome({
        amount: values.amount,
        currency: "USD",
        source: values.source,
        received_on: values.receivedOn,
        payment_method: values.paymentMethod,
      });
      onCreated();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Could not record that income.",
      );
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-3 rounded border border-border p-4"
      noValidate
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="income-amount" className="text-sm font-medium">
            Amount
          </label>
          <input
            id="income-amount"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("amount")}
          />
          {errors.amount ? (
            <p className="mt-1 text-sm text-destructive">
              {errors.amount.message}
            </p>
          ) : null}
        </div>
        <div>
          <label htmlFor="income-source" className="text-sm font-medium">
            Source
          </label>
          <input
            id="income-source"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("source")}
          />
          {errors.source ? (
            <p className="mt-1 text-sm text-destructive">
              {errors.source.message}
            </p>
          ) : null}
        </div>
        <div>
          <label htmlFor="income-received-on" className="text-sm font-medium">
            Date received
          </label>
          <input
            id="income-received-on"
            type="date"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("receivedOn")}
          />
          {errors.receivedOn ? (
            <p className="mt-1 text-sm text-destructive">
              {errors.receivedOn.message}
            </p>
          ) : null}
        </div>
        <div>
          <label
            htmlFor="income-payment-method"
            className="text-sm font-medium"
          >
            Payment method
          </label>
          <input
            id="income-payment-method"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("paymentMethod")}
          />
          {errors.paymentMethod ? (
            <p className="mt-1 text-sm text-destructive">
              {errors.paymentMethod.message}
            </p>
          ) : null}
        </div>
      </div>
      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <Button type="submit" disabled={submitting}>
        {submitting ? "Recording..." : "Record income"}
      </Button>
    </form>
  );
}

function IncomeTable({
  items,
  onDelete,
}: {
  items: Income[];
  onDelete: (incomeId: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Source</th>
            <th className="py-2 font-medium">Date</th>
            <th className="py-2 font-medium">Method</th>
            <th className="py-2 font-medium">Amount</th>
            <th className="py-2 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.id} className="border-b border-border">
              <td className="py-2 font-medium">{row.source}</td>
              <td className="py-2">{row.received_on}</td>
              <td className="py-2">{row.payment_method}</td>
              <td className="py-2">
                {row.currency} {row.amount}
              </td>
              <td className="py-2 text-right">
                <Button variant="outline" onClick={() => onDelete(row.id)}>
                  Delete
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
