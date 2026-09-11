import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import ReportsPage from "@/app/(app)/reports/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

const projectAnalytics = {
  active_projects_count: 2,
  task_completion_rate: 0.5,
  overdue_tasks_count: 3,
  projects: [
    {
      project_id: "project-1",
      name: "Website Redesign",
      status: "ACTIVE",
      task_completion_rate: 0.75,
      overdue_tasks_count: 1,
    },
  ],
};

const leadStats = {
  pipeline_value: "3500.50",
  follow_ups_due: 4,
  conversion_rate: 0.6,
};

const financeStats = {
  revenue_this_month: "1200.00",
  expenses_this_month: "300.00",
  net_cash_flow: "900.00",
  outstanding_invoices_count: 2,
  outstanding_invoices_total: "800.00",
  revenue_trend: [{ month: "2026-01-01", amount: "1200.00" }],
  expense_breakdown: [{ category: "SOFTWARE", amount: "300.00" }],
};

const financeForbidden = {
  error: {
    code: "FORBIDDEN",
    message: "Missing required permission",
    request_id: null,
    details: {},
  },
};

function renderReportsPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ReportsPage />
    </QueryClientProvider>,
  );
}

function mockAllStats({
  finance = financeStats,
  projects = projectAnalytics,
}: {
  finance?: typeof financeStats | typeof financeForbidden;
  projects?: typeof projectAnalytics;
} = {}) {
  server.use(
    http.get(`${APP_ORIGIN}/api/v1/projects/analytics`, () =>
      HttpResponse.json(projects),
    ),
    http.get(`${APP_ORIGIN}/api/v1/leads/stats`, () =>
      HttpResponse.json(leadStats),
    ),
    http.get(`${APP_ORIGIN}/api/v1/finance/stats`, () =>
      finance === financeForbidden
        ? HttpResponse.json(finance, { status: 403 })
        : HttpResponse.json(finance),
    ),
  );
}

describe("ReportsPage", () => {
  it("shows the loading state before data arrives", () => {
    mockAllStats();
    renderReportsPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows Company/Project/Sales/Finance sections once all data loads (OWNER view)", async () => {
    mockAllStats();
    renderReportsPage();
    await waitFor(() =>
      expect(screen.getByText("Website Redesign")).toBeInTheDocument(),
    );
    expect(screen.getByText("Company")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Project" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Sales")).toBeInTheDocument();
    expect(screen.getByText("Finance")).toBeInTheDocument();
    expect(screen.getAllByText("50%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("60%").length).toBeGreaterThan(0);
  });

  it("omits the Finance section for a MEMBER/MANAGER whose finance fetch 403s", async () => {
    mockAllStats({ finance: financeForbidden });
    renderReportsPage();
    await waitFor(() =>
      expect(screen.getByText("Website Redesign")).toBeInTheDocument(),
    );
    expect(screen.getByText("Company")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Project" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Sales")).toBeInTheDocument();
    expect(screen.queryByText("Finance")).not.toBeInTheDocument();
  });

  it("shows the empty state in the Project section when there are no projects", async () => {
    mockAllStats({
      projects: { ...projectAnalytics, projects: [] },
    });
    renderReportsPage();
    await waitFor(() =>
      expect(screen.getByText(/no projects yet/i)).toBeInTheDocument(),
    );
  });

  it("shows the error state when the project-analytics request fails", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/projects/analytics`, () =>
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
      http.get(`${APP_ORIGIN}/api/v1/leads/stats`, () =>
        HttpResponse.json(leadStats),
      ),
      http.get(`${APP_ORIGIN}/api/v1/finance/stats`, () =>
        HttpResponse.json(financeStats),
      ),
    );
    renderReportsPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Missing required permission")).toBeInTheDocument();
  });
});
