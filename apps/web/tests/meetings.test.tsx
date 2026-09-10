import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import MeetingsPage from "@/app/(app)/meetings/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

const meeting = {
  id: "meeting-1",
  title: "Kickoff",
  description: null,
  starts_at: "2026-06-01T10:00:00Z",
  ends_at: "2026-06-01T11:00:00Z",
  client_id: null,
  project_id: null,
  meeting_url: null,
  location: null,
  notes: null,
  external_event_id: null,
  created_by: "01960000-0000-7000-8000-000000000002",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderMeetingsPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MeetingsPage />
    </QueryClientProvider>,
  );
}

describe("MeetingsPage", () => {
  it("shows the loading state before data arrives", () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/meetings`, () =>
        HttpResponse.json({ items: [meeting], total: 1 }),
      ),
    );
    renderMeetingsPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the populated state once meetings load", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/meetings`, () =>
        HttpResponse.json({ items: [meeting], total: 1 }),
      ),
    );
    renderMeetingsPage();
    await waitFor(() =>
      expect(screen.getByText("Kickoff")).toBeInTheDocument(),
    );
  });

  it("shows the empty state when there are no meetings", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/meetings`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderMeetingsPage();
    await waitFor(() =>
      expect(screen.getByText(/no meetings yet/i)).toBeInTheDocument(),
    );
  });

  it("shows the error state when the request fails", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/meetings`, () =>
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
    renderMeetingsPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Something broke")).toBeInTheDocument();
  });

  // RBAC.md §2: "Meetings: create/edit own" is granted to every role —
  // unlike Leads/Clients, this control is never gated, so there's no
  // separate MEMBER-hides-it test to mirror leads.test.tsx's own pair.
  it("always shows the create-meeting control, regardless of role", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/meetings`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderMeetingsPage();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New meeting" }),
      ).toBeInTheDocument(),
    );
  });
});
