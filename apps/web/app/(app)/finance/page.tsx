"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import { ApiError, fetchFinanceStats } from "@/lib/api/client";

// MASTER_PROMPT §19's six dashboard tiles, same data already backing the
// main /dashboard page's own two finance tiles (Stage 8) — this page is
// the full breakdown, not a duplicate aggregate.
export default function FinanceOverviewPage() {
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["finance-stats"],
    queryFn: () => fetchFinanceStats(),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Finance</h1>
        <div className="flex gap-2">
          <Link
            href="/finance/income"
            className="inline-flex h-9 items-center justify-center rounded border border-border bg-transparent px-4 text-sm font-medium hover:bg-muted"
          >
            Income
          </Link>
          <Link
            href="/finance/expenses"
            className="inline-flex h-9 items-center justify-center rounded border border-border bg-transparent px-4 text-sm font-medium hover:bg-muted"
          >
            Expenses
          </Link>
          <Link
            href="/invoices"
            className="inline-flex h-9 items-center justify-center rounded bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            Invoices
          </Link>
        </div>
      </div>
      {isLoading ? (
        <ListLoadingState />
      ) : error || !data ? (
        <ListErrorState
          message={
            error instanceof ApiError
              ? error.message
              : "Something went wrong loading finance stats."
          }
          onRetry={() => refetch()}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatTile
              label="Revenue this month"
              value={data.revenue_this_month}
            />
            <StatTile
              label="Expenses this month"
              value={data.expenses_this_month}
            />
            <StatTile label="Net cash flow" value={data.net_cash_flow} />
            <StatTile
              label="Outstanding invoices"
              value={data.outstanding_invoices_total}
              sub={`${data.outstanding_invoices_count} invoice${data.outstanding_invoices_count === 1 ? "" : "s"}`}
            />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded border border-border p-4">
              <h2 className="text-sm font-semibold text-muted-foreground">
                Revenue trend (6 months)
              </h2>
              {data.revenue_trend.length === 0 ? (
                <p className="mt-2 text-sm text-muted-foreground">
                  No income recorded yet.
                </p>
              ) : (
                <ul className="mt-2 space-y-1 text-sm">
                  {data.revenue_trend.map((point) => (
                    <li key={point.month} className="flex justify-between">
                      <span>{point.month}</span>
                      <span className="font-medium">{point.amount}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="rounded border border-border p-4">
              <h2 className="text-sm font-semibold text-muted-foreground">
                Expense breakdown (this month)
              </h2>
              {data.expense_breakdown.length === 0 ? (
                <p className="mt-2 text-sm text-muted-foreground">
                  No expenses recorded this month.
                </p>
              ) : (
                <ul className="mt-2 space-y-1 text-sm">
                  {data.expense_breakdown.map((point) => (
                    <li key={point.category} className="flex justify-between">
                      <span>{point.category}</span>
                      <span className="font-medium">{point.amount}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function StatTile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded border border-border p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {sub ? <p className="mt-1 text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}
