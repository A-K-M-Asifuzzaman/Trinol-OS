"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { KanbanBoard } from "@/components/board/kanban-board";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  fetchProject,
  fetchProjectBoard,
  fetchProjectRisk,
  updateTask,
  type TaskStatus,
} from "@/lib/api/client";

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const queryClient = useQueryClient();

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
  });
  const boardQuery = useQuery({
    queryKey: ["project-board", projectId],
    queryFn: () => fetchProjectBoard(projectId),
  });
  const [moveError, setMoveError] = useState<string | null>(null);

  async function handleMoveTask(
    taskId: string,
    status: TaskStatus,
    boardPosition: string,
  ) {
    setMoveError(null);
    try {
      await updateTask(taskId, { status, board_position: boardPosition });
      queryClient.invalidateQueries({ queryKey: ["project-board", projectId] });
    } catch (err) {
      setMoveError(
        err instanceof ApiError ? err.message : "Could not move that task.",
      );
    }
  }

  if (projectQuery.isLoading || boardQuery.isLoading) {
    return <ListLoadingState />;
  }

  const firstError = projectQuery.error ?? boardQuery.error;
  if (firstError || !projectQuery.data || !boardQuery.data) {
    return (
      <ListErrorState
        message={
          firstError instanceof ApiError
            ? firstError.message
            : "Something went wrong loading this project."
        }
        onRetry={() => {
          projectQuery.refetch();
          boardQuery.refetch();
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-3xl font-bold">{projectQuery.data.name}</h1>
          <p className="text-sm text-muted-foreground">
            {projectQuery.data.project_code}
          </p>
        </div>
        <Badge>{projectQuery.data.status}</Badge>
        <Badge>{projectQuery.data.health}</Badge>
      </div>
      {moveError ? (
        <p role="alert" className="text-sm text-destructive">
          {moveError}
        </p>
      ) : null}
      <KanbanBoard
        columns={boardQuery.data.columns}
        onMoveTask={handleMoveTask}
      />
      <ProjectRiskPanel projectId={projectId} />
    </div>
  );
}

// Phase 8 Stage 6: `retry: false` for the same "an AI-provider call is
// bounded and shouldn't be retried automatically" reason every other AI
// panel in this app already follows — a slow first-time assessment is
// not a transient failure to retry into a second real API call.
function ProjectRiskPanel({ projectId }: { projectId: string }) {
  const risk = useQuery({
    queryKey: ["project-risk", projectId],
    queryFn: () => fetchProjectRisk(projectId),
    retry: false,
  });

  if (risk.isLoading) {
    return (
      <div className="rounded border border-border p-4 text-sm text-muted-foreground">
        Assessing project risk...
      </div>
    );
  }
  if (!risk.data) return null;

  return (
    <div className="rounded border border-border p-4">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-muted-foreground">
          AI risk assessment
        </h3>
        <Badge>{risk.data.level}</Badge>
      </div>
      {risk.data.narrative ? (
        <p className="mt-2 text-sm">{risk.data.narrative}</p>
      ) : null}
    </div>
  );
}
