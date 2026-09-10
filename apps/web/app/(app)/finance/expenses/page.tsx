"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  createExpense,
  deleteExpense,
  deleteExpenseReceipt,
  fetchExpenses,
  uploadExpenseReceipt,
  type Expense,
  type ExpenseCategory,
} from "@/lib/api/client";

const CATEGORY_OPTIONS: ExpenseCategory[] = [
  "HOSTING",
  "DOMAINS",
  "SOFTWARE",
  "MARKETING",
  "SALARY",
  "CONTRACTOR",
  "OFFICE",
  "TRAVEL",
  "EQUIPMENT",
  "OTHER",
];

// Same client-rendered/four-state pattern as Income. No edit UI for
// expense fields this stage (same ponytail scope decision) — receipt
// upload/download/delete is the one extra lifecycle Income doesn't have.
export default function ExpensesPage() {
  const queryClient = useQueryClient();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["expenses"],
    queryFn: () => fetchExpenses({ limit: 50, offset: 0 }),
  });
  const [showForm, setShowForm] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["expenses"] });
  }

  async function handleDelete(expenseId: string) {
    setRowError(null);
    try {
      await deleteExpense(expenseId);
      invalidate();
    } catch (err) {
      setRowError(
        err instanceof ApiError ? err.message : "Could not delete that row.",
      );
    }
  }

  async function handleUploadReceipt(expenseId: string, file: File) {
    setRowError(null);
    try {
      await uploadExpenseReceipt(expenseId, file);
      invalidate();
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not upload that receipt.",
      );
    }
  }

  async function handleDeleteReceipt(expenseId: string) {
    setRowError(null);
    try {
      await deleteExpenseReceipt(expenseId);
      invalidate();
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not remove that receipt.",
      );
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Expenses</h1>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "New expense"}
        </Button>
      </div>
      {showForm ? (
        <CreateExpenseForm
          onCreated={() => {
            setShowForm(false);
            invalidate();
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
              : "Something went wrong loading expenses."
          }
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <ListEmptyState
          title="No expenses recorded yet"
          description="Record one to get started."
        />
      ) : (
        <ExpenseTable
          items={data.items}
          onDelete={handleDelete}
          onUploadReceipt={handleUploadReceipt}
          onDeleteReceipt={handleDeleteReceipt}
        />
      )}
    </div>
  );
}

const createExpenseSchema = z.object({
  amount: z.string().regex(/^\d+(\.\d{1,2})?$/, "Enter a valid amount"),
  category: z.string().min(1),
  description: z.string().min(1, "Description is required"),
  spentOn: z.string().min(1, "Date is required"),
  paymentMethod: z.string().min(1, "Payment method is required"),
});
type CreateExpenseValues = z.infer<typeof createExpenseSchema>;

function CreateExpenseForm({ onCreated }: { onCreated: () => void }) {
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateExpenseValues>({
    resolver: zodResolver(createExpenseSchema),
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    setSubmitting(true);
    try {
      await createExpense({
        amount: values.amount,
        currency: "USD",
        category: values.category as ExpenseCategory,
        description: values.description,
        spent_on: values.spentOn,
        payment_method: values.paymentMethod,
      });
      onCreated();
    } catch (err) {
      setFormError(
        err instanceof ApiError
          ? err.message
          : "Could not record that expense.",
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
          <label htmlFor="expense-amount" className="text-sm font-medium">
            Amount
          </label>
          <input
            id="expense-amount"
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
          <label htmlFor="expense-category" className="text-sm font-medium">
            Category
          </label>
          <select
            id="expense-category"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            defaultValue="OTHER"
            {...register("category")}
          >
            {CATEGORY_OPTIONS.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="expense-description" className="text-sm font-medium">
            Description
          </label>
          <input
            id="expense-description"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("description")}
          />
          {errors.description ? (
            <p className="mt-1 text-sm text-destructive">
              {errors.description.message}
            </p>
          ) : null}
        </div>
        <div>
          <label htmlFor="expense-spent-on" className="text-sm font-medium">
            Date
          </label>
          <input
            id="expense-spent-on"
            type="date"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("spentOn")}
          />
          {errors.spentOn ? (
            <p className="mt-1 text-sm text-destructive">
              {errors.spentOn.message}
            </p>
          ) : null}
        </div>
        <div>
          <label
            htmlFor="expense-payment-method"
            className="text-sm font-medium"
          >
            Payment method
          </label>
          <input
            id="expense-payment-method"
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
        {submitting ? "Recording..." : "Record expense"}
      </Button>
    </form>
  );
}

function ExpenseTable({
  items,
  onDelete,
  onUploadReceipt,
  onDeleteReceipt,
}: {
  items: Expense[];
  onDelete: (expenseId: string) => void;
  onUploadReceipt: (expenseId: string, file: File) => void;
  onDeleteReceipt: (expenseId: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Description</th>
            <th className="py-2 font-medium">Category</th>
            <th className="py-2 font-medium">Date</th>
            <th className="py-2 font-medium">Amount</th>
            <th className="py-2 font-medium">Receipt</th>
            <th className="py-2 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <ExpenseRow
              key={row.id}
              row={row}
              onDelete={onDelete}
              onUploadReceipt={onUploadReceipt}
              onDeleteReceipt={onDeleteReceipt}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExpenseRow({
  row,
  onDelete,
  onUploadReceipt,
  onDeleteReceipt,
}: {
  row: Expense;
  onDelete: (expenseId: string) => void;
  onUploadReceipt: (expenseId: string, file: File) => void;
  onDeleteReceipt: (expenseId: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <tr className="border-b border-border">
      <td className="py-2 font-medium">{row.description}</td>
      <td className="py-2">
        <Badge>{row.category}</Badge>
      </td>
      <td className="py-2">{row.spent_on}</td>
      <td className="py-2">
        {row.currency} {row.amount}
      </td>
      <td className="py-2">
        {row.receipt_file_id ? (
          <div className="flex items-center gap-2">
            <a
              href={`/api/v1/finance/expenses/${row.id}/receipt`}
              className="text-primary hover:underline"
            >
              View
            </a>
            <Button variant="outline" onClick={() => onDeleteReceipt(row.id)}>
              Remove
            </Button>
          </div>
        ) : (
          <>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onUploadReceipt(row.id, file);
                e.target.value = "";
              }}
            />
            <Button
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
            >
              Upload
            </Button>
          </>
        )}
      </td>
      <td className="py-2 text-right">
        <Button variant="outline" onClick={() => onDelete(row.id)}>
          Delete
        </Button>
      </td>
    </tr>
  );
}
