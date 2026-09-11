import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import DocumentsPage from "@/app/(app)/documents/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

const document = {
  id: "document-1",
  title: "Website redesign brief",
  url: "https://drive.google.com/test",
  kind: "GOOGLE_DRIVE",
  // Matches the global /api/v1/projects handler's own seeded project id
  // (msw/handlers.ts) so the populated-state test can assert the real
  // linked-project name renders, not just that a row appears.
  project_id: "01960000-0000-7000-8000-000000000010",
  client_id: null,
  meeting_id: null,
  added_by: "01960000-0000-7000-8000-000000000002",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderDocumentsPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DocumentsPage />
    </QueryClientProvider>,
  );
}

// DocumentTable always looks up project/client/meeting names for the
// "Linked to" column, regardless of which (if any) a given document uses —
// every populated-state test needs all three mocked (onUnhandledRequest:
// "error", tests/setup.ts) even though /api/v1/projects already has a
// global handler in msw/handlers.ts.
function mockEmptyClientsAndMeetings() {
  server.use(
    http.get(`${APP_ORIGIN}/api/v1/clients`, () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get(`${APP_ORIGIN}/api/v1/meetings`, () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
  );
}

describe("DocumentsPage", () => {
  it("shows the loading state before data arrives", () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/documents`, () =>
        HttpResponse.json({ items: [document], total: 1 }),
      ),
    );
    renderDocumentsPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the populated state once documents load, with the linked project name", async () => {
    mockEmptyClientsAndMeetings();
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/documents`, () =>
        HttpResponse.json({ items: [document], total: 1 }),
      ),
    );
    renderDocumentsPage();
    await waitFor(() =>
      expect(screen.getByText("Website redesign brief")).toBeInTheDocument(),
    );
    expect(screen.getByText("Google Drive")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("Website Redesign")).toBeInTheDocument(),
    );
  });

  it("shows the empty state when there are no documents", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/documents`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderDocumentsPage();
    await waitFor(() =>
      expect(screen.getByText(/no documents yet/i)).toBeInTheDocument(),
    );
  });

  it("shows the error state when the request fails", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/documents`, () =>
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
    );
    renderDocumentsPage();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Missing required permission")).toBeInTheDocument();
  });

  it("shows the create-document form with a kind and link-to picker", async () => {
    mockEmptyClientsAndMeetings();
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/documents`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
    renderDocumentsPage();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New document" }),
      ).toBeInTheDocument(),
    );
    screen.getByRole("button", { name: "New document" }).click();
    await waitFor(() =>
      expect(screen.getByLabelText("Title")).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Kind")).toBeInTheDocument();
    expect(screen.getByLabelText("Link to")).toBeInTheDocument();
  });
});
