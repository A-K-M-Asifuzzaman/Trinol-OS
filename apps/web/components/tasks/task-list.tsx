"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  createTask,
  fetchProjects,
  fetchTasks,
  type Task,
} from "@/lib/api/client";

// Backs both /tasks (org-wide, showCreateForm) and /tasks/my (decision 5 —
// assigneeId is resolved server-side from the session by the /tasks/my page
// itself, this component never sees a client-supplied "me" sentinel).
export function TaskListView({
  title,
  assigneeId,
  showCreateForm = false,
}: {
  title: string;
  assigneeId?: string;
  showCreateForm?: boolean;
}) {
  const queryClient = useQueryClient();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["tasks", assigneeId ?? "all"],
    queryFn: () => fetchTasks({ assigneeId, limit: 50, offset: 0 }),
  });
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">{title}</h1>
        {showCreateForm ? (
          <Button onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "New task"}
          </Button>
        ) : null}
      </div>
      {showForm ? (
        <CreateTaskForm
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["tasks"] });
          }}
        />
      ) : null}
      {isLoading ? (
        <ListLoadingState />
      ) : error ? (
        <ListErrorState
          message={
            error instanceof ApiError
              ? error.message
              : "Something went wrong loading tasks."
          }
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <ListEmptyState
          title="No tasks yet"
          description="Create one to get started."
        />
      ) : (
        <TaskTable tasks={data.items} />
      )}
    </div>
  );
}

const createTaskSchema = z.object({
  title: z.string().min(1, "Title is required"),
  project_id: z.string(),
});
type CreateTaskValues = z.infer<typeof createTaskSchema>;

function CreateTaskForm({ onCreated }: { onCreated: () => void }) {
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateTaskValues>({ resolver: zodResolver(createTaskSchema) });
  // A task with no project never appears on any Kanban board (GET
  // /projects/{id}/board groups strictly by project_id) — this picker is
  // what makes "create task, move it on the board" possible at all.
  const projectsQuery = useQuery({
    queryKey: ["projects-for-task-form"],
    queryFn: () => fetchProjects({ limit: 200 }),
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    setSubmitting(true);
    try {
      // status/priority have server-side defaults (schemas.py), but
      // openapi-typescript still generates them as required fields — pass
      // the same defaults explicitly rather than fighting the generator.
      await createTask({
        title: values.title,
        project_id: values.project_id || null,
        status: "TODO",
        priority: "MEDIUM",
      });
      onCreated();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Could not create task.",
      );
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-3 rounded border border-border p-4"
      noValidate
    >
      <div>
        <label htmlFor="title" className="text-sm font-medium">
          Title
        </label>
        <input
          id="title"
          className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          {...register("title")}
        />
        {errors.title ? (
          <p className="mt-1 text-sm text-destructive">
            {errors.title.message}
          </p>
        ) : null}
      </div>
      <div>
        <label htmlFor="project_id" className="text-sm font-medium">
          Project (optional)
        </label>
        <select
          id="project_id"
          className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          defaultValue=""
          {...register("project_id")}
        >
          <option value="">No project</option>
          {(projectsQuery.data?.items ?? []).map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </div>
      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <Button type="submit" disabled={submitting}>
        {submitting ? "Creating..." : "Create task"}
      </Button>
    </form>
  );
}

function TaskTable({ tasks }: { tasks: Task[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Title</th>
            <th className="py-2 font-medium">Status</th>
            <th className="py-2 font-medium">Priority</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id} className="border-b border-border">
              <td className="py-2">
                <Link
                  href={`/tasks/${task.id}`}
                  className="font-medium hover:underline"
                >
                  {task.title}
                </Link>
              </td>
              <td className="py-2">
                <Badge>{task.status}</Badge>
              </td>
              <td className="py-2">
                <Badge>{task.priority}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
