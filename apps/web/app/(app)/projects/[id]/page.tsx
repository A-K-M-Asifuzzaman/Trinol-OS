"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { KanbanBoard } from "@/components/board/kanban-board";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  fetchProject,
  fetchProjectBoard,
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

  async function handleMoveTask(
    taskId: string,
    status: TaskStatus,
    boardPosition: string,
  ) {
    await updateTask(taskId, { status, board_position: boardPosition });
    queryClient.invalidateQueries({ queryKey: ["project-board", projectId] });
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
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{projectQuery.data.name}</h1>
          <p className="text-sm text-muted-foreground">
            {projectQuery.data.project_code}
          </p>
        </div>
        <Badge>{projectQuery.data.status}</Badge>
        <Badge>{projectQuery.data.health}</Badge>
      </div>
      <KanbanBoard
        columns={boardQuery.data.columns}
        onMoveTask={handleMoveTask}
      />
    </div>
  );
}
