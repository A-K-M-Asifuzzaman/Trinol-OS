"use client";

import Link from "next/link";
import { useState } from "react";
import type { LeadStage, PipelineColumn } from "@/lib/api/client";

const STAGE_LABELS: Record<LeadStage, string> = {
  NEW: "New",
  CONTACTED: "Contacted",
  MEETING: "Meeting",
  PROPOSAL: "Proposal",
  NEGOTIATION: "Negotiation",
  WON: "Won",
  LOST: "Lost",
};

// Duplicated from kanban-board.tsx rather than shared (Stage 8 plan's own
// sanctioned fallback: "a parallel pipeline-board.tsx reusing the same
// drag logic is an acceptable fallback if full generalization proves
// awkward" — the two boards' column labels and card fields differ enough
// that a shared <Board> would need render-prop slots for both, more
// complexity than reuse is worth for two call sites). Same fractional-
// indexing/no-reindexing/no-new-endpoint reasoning as there.
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

export function PipelineBoard({
  columns,
  onMoveLead,
  readOnly = false,
}: {
  columns: PipelineColumn[];
  onMoveLead: (leadId: string, stage: LeadStage, boardPosition: string) => void;
  /** RBAC.md §2: MEMBER views the pipeline read-only — no drag, matching
   * "no edit controls in the UI" for that role, not just a guarded
   * network call. */
  readOnly?: boolean;
}) {
  const [draggingId, setDraggingId] = useState<string | null>(null);

  function dropBeforeIndex(column: PipelineColumn, beforeIndex: number) {
    if (!draggingId) return;
    const before =
      beforeIndex > 0 ? column.leads[beforeIndex - 1].board_position : null;
    const after =
      beforeIndex < column.leads.length
        ? column.leads[beforeIndex].board_position
        : null;
    onMoveLead(draggingId, column.stage, computeBoardPosition(before, after));
    setDraggingId(null);
  }

  return (
    <div className="flex gap-4 overflow-x-auto pb-2">
      {columns.map((column) => (
        <div
          key={column.stage}
          data-testid={`pipeline-column-${column.stage}`}
          className="w-64 shrink-0 rounded border border-border bg-muted/30 p-2"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (!readOnly) dropBeforeIndex(column, column.leads.length);
          }}
        >
          <p className="mb-2 px-1 text-xs font-semibold uppercase text-muted-foreground">
            {STAGE_LABELS[column.stage]} ({column.leads.length})
          </p>
          <div className="space-y-2">
            {column.leads.map((lead, index) => (
              <div
                key={lead.id}
                draggable={!readOnly}
                data-testid={`pipeline-lead-${lead.id}`}
                onDragStart={() => !readOnly && setDraggingId(lead.id)}
                onDragEnd={() => setDraggingId(null)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  if (!readOnly) dropBeforeIndex(column, index);
                }}
                className={`rounded border border-border bg-background p-2 text-sm shadow-sm ${readOnly ? "" : "cursor-move"}`}
              >
                <Link
                  href={`/leads/${lead.id}`}
                  className="font-medium hover:underline"
                >
                  {lead.name}
                </Link>
                {lead.estimated_value ? (
                  <div className="mt-1 text-xs text-muted-foreground">
                    {lead.estimated_value} {lead.currency}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
