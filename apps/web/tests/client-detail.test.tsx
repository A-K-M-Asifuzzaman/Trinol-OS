import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import ClientDetailPage from "@/app/(app)/clients/[id]/page";
import { RoleProvider } from "@/lib/role-context";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "client-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

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

const project = {
  id: "project-1",
  project_code: "ACME1",
  name: "Acme Website",
  description: null,
  client_id: "client-1",
  status: "ACTIVE",
  health: "ON_TRACK",
  owner_id: "01960000-0000-7000-8000-000000000002",
  start_date: null,
  deadline: null,
  budget: null,
  currency: "USD",
  repository_url: null,
  production_url: null,
  staging_url: null,
  archived_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const otherProject = { ...project, id: "project-2", client_id: null };

function renderClientDetailPage(role: string | null = "MANAGER") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RoleProvider role={role}>
        <ClientDetailPage />
      </RoleProvider>
    </QueryClientProvider>,
  );
}

describe("ClientDetailPage", () => {
  it("shows overview fields by default", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/clients/client-1`, () =>
        HttpResponse.json(client),
      ),
    );
    renderClientDetailPage();
    await waitFor(() =>
      expect(screen.getByText("Acme Corp")).toBeInTheDocument(),
    );
    expect(screen.getByText("hello@acme.test")).toBeInTheDocument();
  });

  it("shows only this client's projects on the Projects tab", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/clients/client-1`, () =>
        HttpResponse.json(client),
      ),
      http.get(`${APP_ORIGIN}/api/v1/projects`, () =>
        HttpResponse.json({ items: [project, otherProject], total: 2 }),
      ),
    );
    renderClientDetailPage();
    await waitFor(() =>
      expect(screen.getByText("Acme Corp")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Projects" }));

    await waitFor(() =>
      expect(screen.getByText("Acme Website")).toBeInTheDocument(),
    );
    // otherProject has client_id: null — must not appear on this tab.
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("shows an empty-state-only Invoices tab (Phase 5 entity, not built yet)", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/clients/client-1`, () =>
        HttpResponse.json(client),
      ),
    );
    renderClientDetailPage();
    await waitFor(() =>
      expect(screen.getByText("Acme Corp")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Invoices" }));
    expect(screen.getByText(/no invoices yet/i)).toBeInTheDocument();
  });

  it("hides the archive control for a MEMBER (RBAC.md §2: view-only)", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/clients/client-1`, () =>
        HttpResponse.json(client),
      ),
    );
    renderClientDetailPage("MEMBER");
    await waitFor(() =>
      expect(screen.getByText("Acme Corp")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "Archive client" }),
    ).not.toBeInTheDocument();
  });
});
