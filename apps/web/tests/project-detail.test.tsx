import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import ProjectDetailPage from "@/app/(app)/projects/[id]/page";
import { APP_ORIGIN } from "./msw/handlers";
import { server } from "./msw/server";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "project-1" }),
}));

const project = {
  id: "project-1",
  project_code: "WEB",
  name: "Website Redesign",
  description: null,
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

const task = {
  id: "task-1",
  project_id: "project-1",
  title: "Task A",
  description: null,
  status: "TODO",
  priority: "MEDIUM",
  assignee_id: null,
  created_by: "01960000-0000-7000-8000-000000000002",
  milestone_id: null,
  due_date: null,
  start_date: null,
  estimated_hours: null,
  actual_hours: null,
  tags: null,
  board_position: "0",
  completed_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function boardWith(tasks: (typeof task)[]) {
  return {
    columns: [
      { status: "TODO", tasks },
      { status: "IN_PROGRESS", tasks: [] },
      { status: "REVIEW", tasks: [] },
      { status: "DONE", tasks: [] },
      { status: "CANCELLED", tasks: [] },
    ],
    total: tasks.length,
    truncated: false,
  };
}

function renderProjectDetailPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ProjectDetailPage />
    </QueryClientProvider>,
  );
}

describe("ProjectDetailPage", () => {
  it("shows a message when moving a task fails, rather than failing silently", async () => {
    server.use(
      http.get(`${APP_ORIGIN}/api/v1/projects/project-1`, () =>
        HttpResponse.json(project),
      ),
      http.get(`${APP_ORIGIN}/api/v1/projects/project-1/board`, () =>
        HttpResponse.json(boardWith([task])),
      ),
      http.patch(`${APP_ORIGIN}/api/v1/tasks/task-1`, () =>
        HttpResponse.json(
          {
            error: {
              code: "INTERNAL_ERROR",
              message: "Could not move task",
              request_id: null,
              details: {},
            },
          },
          { status: 500 },
        ),
      ),
    );
    renderProjectDetailPage();

    await waitFor(() =>
      expect(screen.getByTestId("board-task-task-1")).toBeInTheDocument(),
    );

    fireEvent.dragStart(screen.getByTestId("board-task-task-1"));
    fireEvent.drop(screen.getByTestId("board-column-DONE"));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Could not move task",
      ),
    );
  });
});
