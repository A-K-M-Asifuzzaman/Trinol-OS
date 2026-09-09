"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  deleteTask,
  fetchTask,
  updateTask,
  type TaskStatus,
} from "@/lib/api/client";

const STATUS_OPTIONS: TaskStatus[] = [
  "TODO",
  "IN_PROGRESS",
  "REVIEW",
  "DONE",
  "CANCELLED",
];

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const taskId = params.id;
  const router = useRouter();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => fetchTask(taskId),
  });

  async function handleStatusChange(status: TaskStatus) {
    setActionError(null);
    try {
      await updateTask(taskId, { status });
      queryClient.invalidateQueries({ queryKey: ["task", taskId] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not update task.",
      );
    }
  }

  async function handleDelete() {
    setActionError(null);
    try {
      await deleteTask(taskId);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      router.push("/tasks");
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not delete task.",
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
            : "Something went wrong loading this task."
        }
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">{data.title}</h1>
        {data.description ? (
          <p className="mt-1 text-sm text-muted-foreground">
            {data.description}
          </p>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Badge>{data.priority}</Badge>
        <label htmlFor="status" className="text-sm font-medium">
          Status
        </label>
        <select
          id="status"
          value={data.status}
          onChange={(e) => handleStatusChange(e.target.value as TaskStatus)}
          className="rounded border border-border px-2 py-1 text-sm"
        >
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      </div>
      {actionError ? (
        <p role="alert" className="text-sm text-destructive">
          {actionError}
        </p>
      ) : null}
      <Button variant="outline" onClick={handleDelete}>
        Delete task
      </Button>
    </div>
  );
}
