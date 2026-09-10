import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import MeetingDetailPage from "@/app/(app)/meetings/[id]/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "meeting-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

const meeting = {
  id: "meeting-1",
  title: "Kickoff",
  description: "Discuss scope.",
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

function renderMeetingDetailPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MeetingDetailPage />
    </QueryClientProvider>,
  );
}

describe("MeetingDetailPage", () => {
  it("shows the meeting title and its Agenda content by default", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/meetings/meeting-1`, () =>
        HttpResponse.json(meeting),
      ),
    );
    renderMeetingDetailPage();
    await waitFor(() =>
      expect(screen.getByText("Kickoff")).toBeInTheDocument(),
    );
    expect(screen.getByText("Discuss scope.")).toBeInTheDocument();
  });

  it("shows a message when deleting the meeting fails, rather than failing silently", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/meetings/meeting-1`, () =>
        HttpResponse.json(meeting),
      ),
      http.delete(`${APP_ORIGIN}/api/v1/meetings/meeting-1`, () =>
        HttpResponse.json(
          {
            error: {
              code: "FORBIDDEN",
              message: "Insufficient permission to delete this meeting",
              request_id: null,
              details: {},
            },
          },
          { status: 403 },
        ),
      ),
    );
    renderMeetingDetailPage();
    await waitFor(() =>
      expect(screen.getByText("Kickoff")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete meeting" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Insufficient permission to delete this meeting",
      ),
    );
  });

  it("loads attendees and adds one when the Attendees tab is used", async () => {
    let added = false;
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/meetings/meeting-1`, () =>
        HttpResponse.json(meeting),
      ),
      // Stateful: empty until the POST below succeeds, then the refetch
      // (triggered by invalidateQueries) sees the new row — same reason
      // as the promote test's own counter, not two competing handlers.
      http.get(`${APP_ORIGIN}/api/v1/meetings/meeting-1/participants`, () =>
        HttpResponse.json(
          added
            ? {
                items: [
                  {
                    id: "participant-1",
                    meeting_id: "meeting-1",
                    user_id: null,
                    external_email: "guest@example.test",
                    response: "PENDING",
                  },
                ],
                total: 1,
              }
            : { items: [], total: 0 },
        ),
      ),
      http.get(`${APP_ORIGIN}/api/v1/memberships`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
      http.post(`${APP_ORIGIN}/api/v1/meetings/meeting-1/participants`, () => {
        added = true;
        return HttpResponse.json(
          {
            id: "participant-1",
            meeting_id: "meeting-1",
            user_id: null,
            external_email: "guest@example.test",
            response: "PENDING",
          },
          { status: 201 },
        );
      }),
    );
    renderMeetingDetailPage();
    await waitFor(() =>
      expect(screen.getByText("Kickoff")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Attendees" }));
    await waitFor(() =>
      expect(screen.getByText(/no attendees yet/i)).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("Invite"), {
      target: { value: "external" },
    });
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "guest@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add attendee" }));

    await waitFor(() =>
      expect(screen.getByText("guest@example.test")).toBeInTheDocument(),
    );
  });

  it("records a decision from the Decisions tab", async () => {
    let added = false;
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/meetings/meeting-1`, () =>
        HttpResponse.json(meeting),
      ),
      http.get(`${APP_ORIGIN}/api/v1/meetings/meeting-1/decisions`, () =>
        HttpResponse.json(
          added
            ? {
                items: [
                  {
                    id: "decision-1",
                    meeting_id: "meeting-1",
                    body: "We will ship it.",
                    decided_by: "01960000-0000-7000-8000-000000000002",
                    created_at: "2026-01-01T00:00:00Z",
                  },
                ],
                total: 1,
              }
            : { items: [], total: 0 },
        ),
      ),
      http.post(`${APP_ORIGIN}/api/v1/meetings/meeting-1/decisions`, () => {
        added = true;
        return HttpResponse.json(
          {
            id: "decision-1",
            meeting_id: "meeting-1",
            body: "We will ship it.",
            decided_by: "01960000-0000-7000-8000-000000000002",
            created_at: "2026-01-01T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );
    renderMeetingDetailPage();
    await waitFor(() =>
      expect(screen.getByText("Kickoff")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Decisions" }));
    await waitFor(() =>
      expect(screen.getByText(/no decisions yet/i)).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("New decision"), {
      target: { value: "We will ship it." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));

    await waitFor(() =>
      expect(screen.getByText("We will ship it.")).toBeInTheDocument(),
    );
  });

  it("promotes an action item to a task and links to it", async () => {
    let actionsCallCount = 0;
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/meetings/meeting-1`, () =>
        HttpResponse.json(meeting),
      ),
      // First load has task_id: null (not yet promoted); the refetch
      // after invalidateQueries sees task_id set — a stateful counter,
      // not two competing handlers, since MSW checks the most-recently
      // registered handler first regardless of call order.
      http.get(`${APP_ORIGIN}/api/v1/meetings/meeting-1/actions`, () => {
        actionsCallCount += 1;
        return HttpResponse.json({
          items: [
            {
              id: "action-1",
              meeting_id: "meeting-1",
              description: "Send the proposal.",
              owner_id: null,
              due_date: null,
              task_id: actionsCallCount === 1 ? null : "task-1",
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        });
      }),
      http.post(
        `${APP_ORIGIN}/api/v1/meetings/meeting-1/actions/action-1/promote`,
        () =>
          HttpResponse.json(
            { id: "task-1", title: "Send the proposal." },
            { status: 201 },
          ),
      ),
    );
    renderMeetingDetailPage();
    await waitFor(() =>
      expect(screen.getByText("Kickoff")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Action Items" }));
    await waitFor(() =>
      expect(screen.getByText("Send the proposal.")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Promote to task" }));

    await waitFor(() =>
      expect(screen.getByRole("link", { name: "View task" })).toHaveAttribute(
        "href",
        "/tasks/task-1",
      ),
    );
  });
});
