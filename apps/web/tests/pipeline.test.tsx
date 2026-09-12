import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import PipelinePage from "@/app/(app)/pipeline/page";
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

function boardWith(leads: (typeof lead)[]) {
  return {
    columns: [
      { stage: "NEW", leads },
      { stage: "CONTACTED", leads: [] },
      { stage: "MEETING", leads: [] },
      { stage: "PROPOSAL", leads: [] },
      { stage: "NEGOTIATION", leads: [] },
      { stage: "WON", leads: [] },
      { stage: "LOST", leads: [] },
    ],
    total: leads.length,
    truncated: false,
  };
}

function renderPipelinePage(role: string | null = "MANAGER") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RoleProvider role={role}>
        <PipelinePage />
      </RoleProvider>
    </QueryClientProvider>,
  );
}

describe("PipelinePage", () => {
  it("shows a message when moving a lead fails, rather than failing silently", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/pipeline`, () =>
        HttpResponse.json(boardWith([lead])),
      ),
      http.patch(`${APP_ORIGIN}/api/v1/leads/lead-1`, () =>
        HttpResponse.json(
          {
            error: {
              code: "INTERNAL_ERROR",
              message: "Could not move lead",
              request_id: null,
              details: {},
            },
          },
          { status: 500 },
        ),
      ),
    );
    renderPipelinePage();

    await waitFor(() =>
      expect(screen.getByTestId("pipeline-lead-lead-1")).toBeInTheDocument(),
    );

    fireEvent.dragStart(screen.getByTestId("pipeline-lead-lead-1"));
    fireEvent.drop(screen.getByTestId("pipeline-column-WON"));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Could not move lead",
      ),
    );
  });

  it("renders read-only for a MEMBER (RBAC.md §2)", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/pipeline`, () =>
        HttpResponse.json(boardWith([lead])),
      ),
    );
    renderPipelinePage("MEMBER");

    await waitFor(() =>
      expect(screen.getByTestId("pipeline-lead-lead-1")).toHaveAttribute(
        "draggable",
        "false",
      ),
    );
  });

  it("shows a lead's AI score on its card once it has one", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/pipeline`, () =>
        HttpResponse.json(boardWith([lead])),
      ),
      http.get(`${APP_ORIGIN}/api/v1/leads/lead-1/score`, () =>
        HttpResponse.json({
          id: "score-1",
          lead_id: "lead-1",
          score: 55,
          rationale: "Moderate fit.",
          computed_at: "2026-01-01T00:00:00Z",
          computed_by: "01960000-0000-7000-8000-000000000002",
          stale: false,
        }),
      ),
    );
    renderPipelinePage();

    await waitFor(() =>
      expect(screen.getByText("Score: 55/100")).toBeInTheDocument(),
    );
  });
});
