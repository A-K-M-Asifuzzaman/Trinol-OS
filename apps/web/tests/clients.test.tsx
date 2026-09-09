import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import ClientsPage from "@/app/(app)/clients/page";
import { RoleProvider } from "@/lib/role-context";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

const client = {
  id: "client-1",
  name: "Acme Corp",
  company: null,
  email: "hello@acme.test",
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

function renderClientsPage(role: string | null = "MANAGER") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RoleProvider role={role}>
        <ClientsPage />
      </RoleProvider>
    </QueryClientProvider>,
  );
}

describe("ClientsPage", () => {
  it("shows the loading state before data arrives", () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/clients`, () =>
        HttpResponse.json({ items: [client], total: 1 }),
      ),
    );
    renderClientsPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the populated state once clients load", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/clients`, () =>
        HttpResponse.json({ items: [client], total: 1 }),
      ),
    );
    renderClientsPage();
    await waitFor(() =>
      expect(screen.getByText("Acme Corp")).toBeInTheDocument(),
    );
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
  });

  it("shows the empty state when there are no clients", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/clients`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderClientsPage();
    await waitFor(() =>
      expect(screen.getByText(/no clients yet/i)).toBeInTheDocument(),
    );
  });

  it("shows the error state when the request fails", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/clients`, () =>
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
    renderClientsPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Something broke")).toBeInTheDocument();
  });

  it("hides the create-client control for a MEMBER (RBAC.md §2: view-only)", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/clients`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderClientsPage("MEMBER");
    await waitFor(() =>
      expect(screen.getByText(/no clients yet/i)).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "New client" }),
    ).not.toBeInTheDocument();
  });
});
