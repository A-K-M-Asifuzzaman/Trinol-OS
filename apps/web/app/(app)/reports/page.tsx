"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  fetchFinanceStats,
  fetchLeadStats,
  fetchProjectAnalytics,
  type ProjectAnalyticsRow,
} from "@/lib/api/client";

// Phase 7 plan decision 1: Company has no metric of its own — it's a
// frontend-only overview combining one headline figure from each of the
// other three sections, the same Promise-of-independent-fetches shape
// /dashboard already uses (here as three independent useQuery calls
// instead, client-rendered per decision 5/TeamPage's own precedent: the
// Project section below needs its four list states to be MSW-testable,
// which needs a client-side fetch — same reasoning ARCHITECTURE.md §5's
// server-rendered default is departed from everywhere else a list's
// states need testing). No charting library (user-confirmed scope
// decision) — every section renders plain numbers/table rows, same
// convention finance/page.tsx's own revenue-trend/expense-breakdown
// tiles already use.
function formatPercent(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)}%`;
}

export default function ReportsPage() {
  const projectAnalytics = useQuery({
    queryKey: ["project-analytics"],
    queryFn: () => fetchProjectAnalytics(),
  });
  const leadStats = useQuery({
    queryKey: ["lead-stats-reports"],
    queryFn: () => fetchLeadStats(),
  });
  const financeStats = useQuery({
    queryKey: ["finance-stats-reports"],
    queryFn: () => fetchFinanceStats(),
  });

  // Gated on projectAnalytics alone, not all three: leadStats/financeStats
  // render progressively via their own data (StatTiles fall back to "—",
  // Finance is omitted until it has data) instead of blocking the whole
  // page — react-query's default 3-retry-with-backoff behavior means an
  // *expected* 403 from financeStats (a MEMBER/MANAGER) would otherwise
  // keep the entire page on the loading skeleton for several seconds
  // while it retries a request that was never going to succeed.
  return (
    <div className="space-y-8">
      <div className="border-b border-border pb-6">
        <p className="eyebrow mb-2">Business intelligence</p>
        <h1 className="text-3xl font-bold sm:text-4xl">Reports</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Delivery, sales, and finance signals in one view.
        </p>
      </div>
      {projectAnalytics.isLoading ? (
        <ListLoadingState />
      ) : projectAnalytics.error || !projectAnalytics.data ? (
        <ListErrorState
          message={
            projectAnalytics.error instanceof ApiError
              ? projectAnalytics.error.message
              : "Something went wrong loading reports."
          }
          onRetry={() => projectAnalytics.refetch()}
        />
      ) : (
        <>
          <Section title="Company">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <StatTile
                label="Active projects"
                value={String(projectAnalytics.data.active_projects_count)}
              />
              <StatTile
                label="Task completion"
                value={formatPercent(
                  projectAnalytics.data.task_completion_rate,
                )}
              />
              <StatTile
                label="Overdue tasks"
                value={String(projectAnalytics.data.overdue_tasks_count)}
              />
              <StatTile
                label="Pipeline value"
                value={leadStats.data?.pipeline_value ?? "—"}
              />
              <StatTile
                label="Lead conversion"
                value={formatPercent(leadStats.data?.conversion_rate ?? null)}
              />
              {/* RBAC.md §3: omitted entirely for MEMBER/MANAGER (whose own
              fetch above 403s), not shown as "—" — same convention
              /dashboard's own finance tiles already use. */}
              {financeStats.data ? (
                <>
                  <StatTile
                    label="Revenue this month"
                    value={financeStats.data.revenue_this_month}
                  />
                  <StatTile
                    label="Expenses this month"
                    value={financeStats.data.expenses_this_month}
                  />
                </>
              ) : null}
            </div>
          </Section>

          <Section title="Project">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              <StatTile
                label="Active projects"
                value={String(projectAnalytics.data.active_projects_count)}
              />
              <StatTile
                label="Task completion"
                value={formatPercent(
                  projectAnalytics.data.task_completion_rate,
                )}
              />
              <StatTile
                label="Overdue tasks"
                value={String(projectAnalytics.data.overdue_tasks_count)}
              />
            </div>
            {projectAnalytics.data.projects.length === 0 ? (
              <ListEmptyState
                title="No projects yet"
                description="Create one to get started."
              />
            ) : (
              <ProjectTable projects={projectAnalytics.data.projects} />
            )}
          </Section>

          <Section title="Sales">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              <StatTile
                label="Pipeline value"
                value={leadStats.data?.pipeline_value ?? "—"}
              />
              <StatTile
                label="Lead conversion"
                value={formatPercent(leadStats.data?.conversion_rate ?? null)}
              />
              <StatTile
                label="Follow-ups due"
                value={
                  leadStats.data ? String(leadStats.data.follow_ups_due) : "—"
                }
              />
            </div>
          </Section>

          {financeStats.data ? (
            <Section title="Finance">
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <StatTile
                  label="Revenue this month"
                  value={financeStats.data.revenue_this_month}
                />
                <StatTile
                  label="Expenses this month"
                  value={financeStats.data.expenses_this_month}
                />
                <StatTile
                  label="Net cash flow"
                  value={financeStats.data.net_cash_flow}
                />
                <StatTile
                  label="Outstanding invoices"
                  value={financeStats.data.outstanding_invoices_total}
                  sub={`${financeStats.data.outstanding_invoices_count} invoice${financeStats.data.outstanding_invoices_count === 1 ? "" : "s"}`}
                />
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded border border-border p-4">
                  <h3 className="text-sm font-semibold text-muted-foreground">
                    Revenue trend (6 months)
                  </h3>
                  {financeStats.data.revenue_trend.length === 0 ? (
                    <p className="mt-2 text-sm text-muted-foreground">
                      No income recorded yet.
                    </p>
                  ) : (
                    <ul className="mt-2 space-y-1 text-sm">
                      {financeStats.data.revenue_trend.map((point) => (
                        <li key={point.month} className="flex justify-between">
                          <span>{point.month}</span>
                          <span className="font-medium">{point.amount}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="rounded border border-border p-4">
                  <h3 className="text-sm font-semibold text-muted-foreground">
                    Expense breakdown (this month)
                  </h3>
                  {financeStats.data.expense_breakdown.length === 0 ? (
                    <p className="mt-2 text-sm text-muted-foreground">
                      No expenses recorded this month.
                    </p>
                  ) : (
                    <ul className="mt-2 space-y-1 text-sm">
                      {financeStats.data.expense_breakdown.map((point) => (
                        <li
                          key={point.category}
                          className="flex justify-between"
                        >
                          <span>{point.category}</span>
                          <span className="font-medium">{point.amount}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </Section>
          ) : null}
        </>
      )}
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-bold tracking-[-0.02em]">{title}</h2>
        <span className="h-px flex-1 bg-border" />
      </div>
      {children}
    </section>
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
    <div className="surface min-h-28 p-4">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="mt-5 font-mono text-2xl font-semibold tracking-[-0.04em] tabular-nums">
        {value}
      </p>
      {sub ? <p className="mt-1 text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

function ProjectTable({ projects }: { projects: ProjectAnalyticsRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Project</th>
            <th className="py-2 font-medium">Status</th>
            <th className="py-2 font-medium">Task completion</th>
            <th className="py-2 font-medium">Overdue tasks</th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => (
            <tr key={project.project_id} className="border-b border-border">
              <td className="py-2 font-medium">{project.name}</td>
              <td className="py-2">
                <Badge>{project.status}</Badge>
              </td>
              <td className="py-2">
                {formatPercent(project.task_completion_rate)}
              </td>
              <td className="py-2">{project.overdue_tasks_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
