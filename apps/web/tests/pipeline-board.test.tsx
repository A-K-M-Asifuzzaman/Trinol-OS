import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PipelineBoard } from "@/components/board/pipeline-board";
import type { PipelineColumn } from "@/lib/api/client";

function makeLead(id: string, name: string, boardPosition: string) {
  return {
    id,
    name,
    company: null,
    email: `${id}@x.com`,
    phone: null,
    source: "WEBSITE" as const,
    service: null,
    estimated_value: null,
    currency: "USD",
    stage: "NEW" as const,
    assigned_to: null,
    next_follow_up: null,
    notes: null,
    converted_client_id: null,
    converted_at: null,
    lost_reason: null,
    board_position: boardPosition,
    archived_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("PipelineBoard", () => {
  it("drops a lead into an empty column at position 0", () => {
    const onMoveLead = vi.fn();
    const columns: PipelineColumn[] = [
      { stage: "NEW", leads: [makeLead("lead-a", "Lead A", "0")] },
      { stage: "WON", leads: [] },
    ];
    render(<PipelineBoard columns={columns} onMoveLead={onMoveLead} />);

    fireEvent.dragStart(screen.getByTestId("pipeline-lead-lead-a"));
    fireEvent.drop(screen.getByTestId("pipeline-column-WON"));

    expect(onMoveLead).toHaveBeenCalledWith("lead-a", "WON", "0");
  });

  it("drops a lead before an existing card, computing the midpoint position", () => {
    const onMoveLead = vi.fn();
    const columns: PipelineColumn[] = [
      {
        stage: "NEW",
        leads: [
          makeLead("lead-a", "Lead A", "0"),
          makeLead("lead-b", "Lead B", "10"),
        ],
      },
    ];
    render(<PipelineBoard columns={columns} onMoveLead={onMoveLead} />);

    fireEvent.dragStart(screen.getByTestId("pipeline-lead-lead-b"));
    fireEvent.drop(screen.getByTestId("pipeline-lead-lead-a"));

    expect(onMoveLead).toHaveBeenCalledWith("lead-b", "NEW", "-1");
  });

  it("moving the first card past others computes neighbors excluding itself", () => {
    // Codex P1: dropBeforeIndex used to compute neighbors from
    // column.leads while it still contained the dragged lead at its old
    // (earlier) position — dragging the first card forward could then
    // pick the dragged card itself as a neighbor instead of the two
    // cards actually surrounding the drop target. [A, B, C]: dragging A
    // onto C must use B/C as neighbors (A is gone from consideration),
    // not A/C.
    const onMoveLead = vi.fn();
    const columns: PipelineColumn[] = [
      {
        stage: "NEW",
        leads: [
          makeLead("lead-a", "Lead A", "0"),
          makeLead("lead-b", "Lead B", "10"),
          makeLead("lead-c", "Lead C", "20"),
        ],
      },
    ];
    render(<PipelineBoard columns={columns} onMoveLead={onMoveLead} />);

    fireEvent.dragStart(screen.getByTestId("pipeline-lead-lead-a"));
    fireEvent.drop(screen.getByTestId("pipeline-lead-lead-c"));

    // Midpoint of B (10) and C (20) — never a value computed from A's own
    // old position.
    expect(onMoveLead).toHaveBeenCalledWith("lead-a", "NEW", "15");
  });

  it("moving the first card onto its immediate successor never uses the dragged card as a neighbor", () => {
    // The sharpest case: dropping onto the card immediately after the
    // dragged one used to make that successor's *predecessor* resolve to
    // the dragged card itself (still sitting in column.leads at its old
    // index). Once removed from consideration, B has no predecessor left
    // in [A, B, C] minus A, so "before" must be null, not lead A's own
    // position.
    const onMoveLead = vi.fn();
    const columns: PipelineColumn[] = [
      {
        stage: "NEW",
        leads: [
          makeLead("lead-a", "Lead A", "0"),
          makeLead("lead-b", "Lead B", "10"),
          makeLead("lead-c", "Lead C", "20"),
        ],
      },
    ];
    render(<PipelineBoard columns={columns} onMoveLead={onMoveLead} />);

    fireEvent.dragStart(screen.getByTestId("pipeline-lead-lead-a"));
    fireEvent.drop(screen.getByTestId("pipeline-lead-lead-b"));

    // One less than B's position (10) — computeBoardPosition(null, 10).
    expect(onMoveLead).toHaveBeenCalledWith("lead-a", "NEW", "9");
  });

  it("ignores drag/drop entirely when read-only (MEMBER, RBAC.md §2)", () => {
    const onMoveLead = vi.fn();
    const columns: PipelineColumn[] = [
      { stage: "NEW", leads: [makeLead("lead-a", "Lead A", "0")] },
      { stage: "WON", leads: [] },
    ];
    render(
      <PipelineBoard columns={columns} onMoveLead={onMoveLead} readOnly />,
    );

    const card = screen.getByTestId("pipeline-lead-lead-a");
    expect(card).toHaveAttribute("draggable", "false");

    fireEvent.dragStart(card);
    fireEvent.drop(screen.getByTestId("pipeline-column-WON"));

    expect(onMoveLead).not.toHaveBeenCalled();
  });
});
