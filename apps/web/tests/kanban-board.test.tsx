import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KanbanBoard } from "@/components/board/kanban-board";
import type { BoardColumn } from "@/lib/api/client";

function makeTask(id: string, title: string, boardPosition: string) {
  return {
    id,
    project_id: null,
    title,
    description: null,
    status: "TODO" as const,
    priority: "MEDIUM" as const,
    assignee_id: null,
    created_by: "01960000-0000-7000-8000-000000000002",
    milestone_id: null,
    due_date: null,
    start_date: null,
    estimated_hours: null,
    actual_hours: null,
    tags: null,
    board_position: boardPosition,
    completed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("KanbanBoard", () => {
  it("drops a task into an empty column at position 0", () => {
    const onMoveTask = vi.fn();
    const columns: BoardColumn[] = [
      { status: "TODO", tasks: [makeTask("task-a", "Task A", "0")] },
      { status: "DONE", tasks: [] },
    ];
    render(<KanbanBoard columns={columns} onMoveTask={onMoveTask} />);

    fireEvent.dragStart(screen.getByTestId("board-task-task-a"));
    fireEvent.drop(screen.getByTestId("board-column-DONE"));

    expect(onMoveTask).toHaveBeenCalledWith("task-a", "DONE", "0");
  });

  it("drops a task before an existing card, computing the midpoint position", () => {
    const onMoveTask = vi.fn();
    const columns: BoardColumn[] = [
      {
        status: "TODO",
        tasks: [
          makeTask("task-a", "Task A", "0"),
          makeTask("task-b", "Task B", "10"),
        ],
      },
    ];
    render(<KanbanBoard columns={columns} onMoveTask={onMoveTask} />);

    fireEvent.dragStart(screen.getByTestId("board-task-task-b"));
    fireEvent.drop(screen.getByTestId("board-task-task-a"));

    // Dropped before task-a (the first card, no predecessor) — midpoint is
    // "one less than the following card's position", per the same rule used
    // when there's no successor either.
    expect(onMoveTask).toHaveBeenCalledWith("task-b", "TODO", "-1");
  });
});
