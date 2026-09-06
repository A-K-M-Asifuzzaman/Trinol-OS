import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import TeamPage from "@/app/(app)/team/page";
import { API_BASE_URL } from "./msw/handlers";
import { server } from "./msw/server";

// ARCHITECTURE.md §5: "Every list route ships four states ... This is a
// review gate, not a suggestion." All four exercised against MSW, never a
// real API.
function renderTeamPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <TeamPage />
    </QueryClientProvider>,
  );
}

describe("TeamPage", () => {
  it("shows the loading state before data arrives", () => {
    renderTeamPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the populated state once members load", async () => {
    renderTeamPage();
    await waitFor(() =>
      expect(screen.getByText("Ada Lovelace")).toBeInTheDocument(),
    );
    expect(screen.getByText("OWNER")).toBeInTheDocument();
  });

  it("shows the empty state when there are no members", async () => {
    server.use(
      http.get(`${API_BASE_URL}/api/v1/memberships`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderTeamPage();
    await waitFor(() =>
      expect(screen.getByText(/no team members yet/i)).toBeInTheDocument(),
    );
  });

  it("shows the error state when the request fails", async () => {
    server.use(
      http.get(`${API_BASE_URL}/api/v1/memberships`, () =>
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
    renderTeamPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Something broke")).toBeInTheDocument();
  });
});
