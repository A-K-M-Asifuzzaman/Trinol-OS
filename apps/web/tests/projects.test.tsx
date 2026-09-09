import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import ProjectsPage from "@/app/(app)/projects/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

// Same four-state pattern as TeamPage (Stage 10).
function renderProjectsPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ProjectsPage />
    </QueryClientProvider>,
  );
}

describe("ProjectsPage", () => {
  it("shows the loading state before data arrives", () => {
    renderProjectsPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the populated state once projects load", async () => {
    renderProjectsPage();
    await waitFor(() =>
      expect(screen.getByText("Website Redesign")).toBeInTheDocument(),
    );
    expect(screen.getByText("WEB")).toBeInTheDocument();
  });

  it("shows the empty state when there are no projects", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/projects`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderProjectsPage();
    await waitFor(() =>
      expect(screen.getByText(/no projects yet/i)).toBeInTheDocument(),
    );
  });

  it("shows the error state when the request fails", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/projects`, () =>
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
    renderProjectsPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Something broke")).toBeInTheDocument();
  });
});
