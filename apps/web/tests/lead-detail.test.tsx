import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import LeadDetailPage from "@/app/(app)/leads/[id]/page";
import { RoleProvider } from "@/lib/role-context";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "lead-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

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

function renderLeadDetailPage(role: string | null = "MANAGER") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RoleProvider role={role}>
        <LeadDetailPage />
      </RoleProvider>
    </QueryClientProvider>,
  );
}

describe("LeadDetailPage", () => {
  it("shows a message when changing stage fails, rather than failing silently", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads/lead-1`, () =>
        HttpResponse.json(lead),
      ),
      http.patch(`${APP_ORIGIN}/api/v1/leads/lead-1`, () =>
        HttpResponse.json(
          {
            error: {
              code: "INTERNAL_ERROR",
              message: "Could not update the lead",
              request_id: null,
              details: {},
            },
          },
          { status: 500 },
        ),
      ),
    );
    renderLeadDetailPage();

    await waitFor(() =>
      expect(screen.getByText("Jane Prospect")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Stage"), {
      target: { value: "CONTACTED" },
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Could not update the lead",
      ),
    );
  });

  it("shows the convert control for a MANAGER", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads/lead-1`, () =>
        HttpResponse.json(lead),
      ),
    );
    renderLeadDetailPage("MANAGER");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Convert to client" }),
      ).toBeInTheDocument(),
    );
  });

  it("hides the convert control and disables the stage select for a MEMBER (RBAC.md §2)", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads/lead-1`, () =>
        HttpResponse.json(lead),
      ),
    );
    renderLeadDetailPage("MEMBER");
    await waitFor(() => expect(screen.getByLabelText("Stage")).toBeDisabled());
    expect(
      screen.queryByRole("button", { name: "Convert to client" }),
    ).not.toBeInTheDocument();
  });

  it("scores the lead and renders the score and rationale for a MANAGER", async () => {
    let scored = false;
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads/lead-1`, () =>
        HttpResponse.json(lead),
      ),
      http.get(`${APP_ORIGIN}/api/v1/leads/lead-1/score`, () =>
        scored
          ? HttpResponse.json({
              id: "score-1",
              lead_id: "lead-1",
              score: 82,
              rationale: "Strong fit given the estimated value.",
              computed_at: "2026-01-01T00:00:00Z",
              computed_by: "01960000-0000-7000-8000-000000000002",
              stale: false,
            })
          : HttpResponse.json(
              {
                error: {
                  code: "NOT_FOUND",
                  message: "This lead has not been scored yet",
                  request_id: null,
                  details: {},
                },
              },
              { status: 404 },
            ),
      ),
      http.post(`${APP_ORIGIN}/api/v1/leads/lead-1/score`, () => {
        scored = true;
        return HttpResponse.json({
          id: "score-1",
          lead_id: "lead-1",
          score: 82,
          rationale: "Strong fit given the estimated value.",
          computed_at: "2026-01-01T00:00:00Z",
          computed_by: "01960000-0000-7000-8000-000000000002",
          stale: false,
        });
      }),
    );
    renderLeadDetailPage("MANAGER");
    await waitFor(() =>
      expect(screen.getByText("Not scored yet.")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Score" }));

    await waitFor(() =>
      expect(screen.getByText("82 / 100")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("Strong fit given the estimated value."),
    ).toBeInTheDocument();
  });

  it("hides the score/rescore button for a MEMBER", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/leads/lead-1`, () =>
        HttpResponse.json(lead),
      ),
    );
    renderLeadDetailPage("MEMBER");
    await waitFor(() =>
      expect(screen.getByText("Not scored yet.")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "Score" }),
    ).not.toBeInTheDocument();
  });
});
