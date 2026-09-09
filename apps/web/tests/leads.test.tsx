import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import LeadsPage from "@/app/(app)/leads/page";
import { RoleProvider } from "@/lib/role-context";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

const lead = {
  id: "lead-1",
  name: "Jane Prospect",
  company: null,
  email: "jane@prospect.test",
  phone: null,
  source: "WEBSITE",
  service: null,
  estimated_value: null,
  currency: "USD",
  stage: "NEW",
  assigned_to: null,
  next_follow_up: null,
  notes: null,
  converted_client_id: null,
  converted_at: null,
  lost_reason: null,
  board_position: "0",
  archived_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderLeadsPage(role: string | null = "MANAGER") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RoleProvider role={role}>
        <LeadsPage />
      </RoleProvider>
    </QueryClientProvider>,
  );
}

describe("LeadsPage", () => {
  it("shows the loading state before data arrives", () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads`, () =>
        HttpResponse.json({ items: [lead], total: 1 }),
      ),
    );
    renderLeadsPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the populated state once leads load", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads`, () =>
        HttpResponse.json({ items: [lead], total: 1 }),
      ),
    );
    renderLeadsPage();
    await waitFor(() =>
      expect(screen.getByText("Jane Prospect")).toBeInTheDocument(),
    );
    expect(screen.getByText("NEW")).toBeInTheDocument();
  });

  it("shows the empty state when there are no leads", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderLeadsPage();
    await waitFor(() =>
      expect(screen.getByText(/no leads yet/i)).toBeInTheDocument(),
    );
  });

  it("shows the error state when the request fails", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads`, () =>
        HttpResponse.json(
          {
            error: {
              code: "INTERNAL_ERROR",
              message: "Something broke",
              request_id: null,
              details: {},
            },
          },
          { status: 500 },
        ),
      ),
    );
    renderLeadsPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Something broke")).toBeInTheDocument();
  });

  it("shows the create-lead control for a MANAGER", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderLeadsPage("MANAGER");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New lead" }),
      ).toBeInTheDocument(),
    );
  });

  it("hides the create-lead control for a MEMBER (RBAC.md §2: view-only)", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderLeadsPage("MEMBER");
    await waitFor(() =>
      expect(screen.getByText(/no leads yet/i)).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "New lead" }),
    ).not.toBeInTheDocument();
  });
});
