"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import {
  fetchLeadScore,
  type LeadStage,
  type PipelineColumn,
} from "@/lib/api/client";

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

  // Codex P1: column.leads still contains the dragged lead at its old
  // position, so computing neighbors by raw index against that array can
  // pick the dragged lead itself as a neighbor (or shift the target's
  // effective position) once it's reordered downward past other cards.
  // Filtering the dragged lead out first, then locating the target by id
  // in that filtered list, removes the index arithmetic that made this
  // possible to get wrong — every neighbor lookup below only ever sees
  // cards other than the one being moved.
  function dropBeforeLead(column: PipelineColumn, targetLeadId: string | null) {
    if (!draggingId) return;
    const remaining = column.leads.filter((lead) => lead.id !== draggingId);
    const targetIndex =
      targetLeadId === null
        ? remaining.length
        : remaining.findIndex((lead) => lead.id === targetLeadId);
    if (targetIndex === -1) {
      // Dropped onto its own card (targetLeadId === draggingId) — no-op.
      setDraggingId(null);
      return;
    }
    const before =
      targetIndex > 0 ? remaining[targetIndex - 1].board_position : null;
    const after =
      targetIndex < remaining.length
        ? remaining[targetIndex].board_position
        : null;
    onMoveLead(draggingId, column.stage, computeBoardPosition(before, after));
    setDraggingId(null);
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-3">
      {columns.map((column) => (
        <div
          key={column.stage}
          data-testid={`pipeline-column-${column.stage}`}
          className="w-72 shrink-0 rounded border border-border bg-muted/45 p-2.5 shadow-[inset_0_3px_0_hsl(var(--foreground)/0.12)]"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (!readOnly) dropBeforeLead(column, null);
          }}
        >
          <div className="mb-2.5 flex items-center justify-between px-1 py-1">
            <p className="text-[11px] font-bold tracking-[0.08em] text-muted-foreground uppercase">
              {STAGE_LABELS[column.stage]}
            </p>
            <span className="grid h-6 min-w-6 place-items-center rounded-sm border border-border bg-white px-1.5 font-mono text-[10px] font-bold tabular-nums">
              {column.leads.length}
            </span>
          </div>
          <div className="space-y-2">
            {column.leads.map((lead) => (
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
                  if (!readOnly) dropBeforeLead(column, lead.id);
                }}
                className={`group rounded border border-border bg-white p-3 text-sm shadow-[0_1px_1px_hsl(var(--foreground)/0.04)] transition hover:-translate-y-0.5 hover:border-foreground/35 hover:shadow-md ${readOnly ? "" : "cursor-move"}`}
              >
                <Link
                  href={`/leads/${lead.id}`}
                  className="font-semibold leading-snug hover:underline"
                >
                  {lead.name}
                </Link>
                {lead.estimated_value ? (
                  <div className="mt-3 font-mono text-xs text-muted-foreground tabular-nums">
                    {lead.estimated_value} {lead.currency}
                  </div>
                ) : null}
                <PipelineLeadScoreBadge leadId={lead.id} />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// Phase 8 Stage 5: an unscored lead (or one this viewer can't see for
// some other reason) simply renders nothing — same "degrade gracefully,
// no error UI" pattern the Reports page already uses for an omitted
// Finance tile, not every card needs a score to be useful.
function PipelineLeadScoreBadge({ leadId }: { leadId: string }) {
  const score = useQuery({
    queryKey: ["lead-score", leadId],
    queryFn: () => fetchLeadScore(leadId),
    retry: false,
  });
  if (!score.data) return null;
  return (
    <div className="mt-2 inline-flex rounded-sm bg-muted px-1.5 py-0.5 font-mono text-[10px] font-bold text-muted-foreground tabular-nums">
      Score: {score.data.score}/100
    </div>
  );
}
