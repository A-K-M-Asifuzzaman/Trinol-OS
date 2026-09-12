"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PipelineBoard } from "@/components/board/pipeline-board";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  fetchPipeline,
  updateLead,
  type LeadStage,
} from "@/lib/api/client";
import { useCanManageCrm } from "@/lib/role-context";

export default function PipelinePage() {
  const queryClient = useQueryClient();
  const canManage = useCanManageCrm();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["pipeline"],
    queryFn: () => fetchPipeline(),
  });
  const [moveError, setMoveError] = useState<string | null>(null);

  async function handleMoveLead(
    leadId: string,
    stage: LeadStage,
    boardPosition: string,
  ) {
    if (!canManage) return;
    setMoveError(null);
    try {
      await updateLead(leadId, { stage, board_position: boardPosition });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    } catch (err) {
      setMoveError(
        err instanceof ApiError ? err.message : "Could not move that lead.",
      );
    }
  }

  if (isLoading) return <ListLoadingState />;
  if (error || !data) {
    return (
      <ListErrorState
        message={
          error instanceof ApiError
            ? error.message
            : "Something went wrong loading the pipeline."
        }
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-3xl font-bold">Pipeline</h1>
        {data.truncated ? (
          <p className="text-sm text-muted-foreground">
            Showing the first leads of {data.total} total.
          </p>
        ) : null}
      </div>
      {moveError ? (
        <p role="alert" className="text-sm text-destructive">
          {moveError}
        </p>
      ) : null}
      <PipelineBoard
        columns={data.columns}
        onMoveLead={handleMoveLead}
        readOnly={!canManage}
      />
    </div>
  );
}
