"use client";

import Link from "next/link";
import { useState } from "react";
import type { BoardColumn, TaskStatus } from "@/lib/api/client";

const STATUS_LABELS: Record<TaskStatus, string> = {
  TODO: "To Do",
  IN_PROGRESS: "In Progress",
  REVIEW: "Review",
  DONE: "Done",
  CANCELLED: "Cancelled",
};

// Stage 4 decision 1: board_position is a fractional-indexing sort key, so a
// drop between two cards is the midpoint of their positions — no reindexing
// of the rest of the column, no new reorder endpoint (the existing PATCH
// /tasks/{id} already accepts board_position). `ponytail: plain float
// arithmetic, not arbitrary-precision — repeated drops onto the exact same
// slot will eventually run out of representable midpoints; a real reorder
// endpoint with rebalancing is the fix if that's ever observed in practice`
// (already logged in ROADMAP.md's technical debt ledger as the no-collision-
// handling gap this decision accepted).
function computeBoardPosition(before: string | null, after: string | null): string {
  const b = before === null ? null : Number(before);
  const a = after === null ? null : Number(after);
  if (b === null && a === null) return "0";
  if (b === null) return String(a! - 1);
  if (a === null) return String(b + 1);
  return String((a + b) / 2);
}

export function KanbanBoard({
  columns,
  onMoveTask,
}: {
  columns: BoardColumn[];
  onMoveTask: (taskId: string, status: TaskStatus, boardPosition: string) => void;
}) {
  const [draggingId, setDraggingId] = useState<string | null>(null);

  function dropBeforeIndex(column: BoardColumn, beforeIndex: number) {
    if (!draggingId) return;
    const before =
      beforeIndex > 0 ? column.tasks[beforeIndex - 1].board_position : null;
    const after =
      beforeIndex < column.tasks.length
        ? column.tasks[beforeIndex].board_position
        : null;
    onMoveTask(
      draggingId,
      column.status,
      computeBoardPosition(before, after),
    );
    setDraggingId(null);
  }

  return (
    <div className="flex gap-4 overflow-x-auto pb-2">
      {columns.map((column) => (
        <div
          key={column.status}
          data-testid={`board-column-${column.status}`}
          className="w-64 shrink-0 rounded border border-border bg-muted/30 p-2"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            dropBeforeIndex(column, column.tasks.length);
          }}
        >
          <p className="mb-2 px-1 text-xs font-semibold uppercase text-muted-foreground">
            {STATUS_LABELS[column.status]} ({column.tasks.length})
          </p>
          <div className="space-y-2">
            {column.tasks.map((task, index) => (
              <div
                key={task.id}
                draggable
                data-testid={`board-task-${task.id}`}
                onDragStart={() => setDraggingId(task.id)}
                onDragEnd={() => setDraggingId(null)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  dropBeforeIndex(column, index);
                }}
                className="cursor-move rounded border border-border bg-background p-2 text-sm shadow-sm"
              >
                <Link
                  href={`/tasks/${task.id}`}
                  className="font-medium hover:underline"
                >
                  {task.title}
                </Link>
                <div className="mt-1 text-xs text-muted-foreground">
                  {task.priority}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
