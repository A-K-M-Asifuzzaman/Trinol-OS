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
function computeBoardPosition(
  before: string | null,
  after: string | null,
): string {
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
  onMoveTask: (
    taskId: string,
    status: TaskStatus,
    boardPosition: string,
  ) => void;
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
    onMoveTask(draggingId, column.status, computeBoardPosition(before, after));
    setDraggingId(null);
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-3">
      {columns.map((column) => (
        <div
          key={column.status}
          data-testid={`board-column-${column.status}`}
          className="w-72 shrink-0 rounded border border-border bg-muted/45 p-2.5 shadow-[inset_0_3px_0_hsl(var(--foreground)/0.12)]"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            dropBeforeIndex(column, column.tasks.length);
          }}
        >
          <div className="mb-2.5 flex items-center justify-between px-1 py-1">
            <p className="text-[11px] font-bold tracking-[0.08em] text-muted-foreground uppercase">
              {STATUS_LABELS[column.status]}
            </p>
            <span className="grid h-6 min-w-6 place-items-center rounded-sm border border-border bg-white px-1.5 font-mono text-[10px] font-bold tabular-nums">
              {column.tasks.length}
            </span>
          </div>
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
                className="group cursor-move rounded border border-border bg-white p-3 text-sm shadow-[0_1px_1px_hsl(var(--foreground)/0.04)] transition hover:-translate-y-0.5 hover:border-foreground/35 hover:shadow-md"
              >
                <Link
                  href={`/tasks/${task.id}`}
                  className="font-semibold leading-snug hover:underline"
                >
                  {task.title}
                </Link>
                <div className="mt-3 flex items-center gap-1.5 text-[10px] font-bold tracking-[0.06em] text-muted-foreground uppercase">
                  <span className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--signal))] ring-1 ring-foreground/15" />
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
