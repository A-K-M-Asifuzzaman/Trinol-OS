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
  createProject,
  fetchProjects,
  type Project,
} from "@/lib/api/client";

// Same client-rendered/four-state pattern as Team (Stage 10) — see that
// page's own comment for why this departs from ARCHITECTURE.md §5's
// server-rendered default.
export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["projects"],
    queryFn: () => fetchProjects({ limit: 50, offset: 0 }),
  });
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Projects</h1>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "New project"}
        </Button>
      </div>
      {showForm ? (
        <CreateProjectForm
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["projects"] });
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
              : "Something went wrong loading projects."
          }
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <ListEmptyState
          title="No projects yet"
          description="Create one to get started."
        />
      ) : (
        <ProjectTable projects={data.items} />
      )}
    </div>
  );
}

const createProjectSchema = z.object({
  project_code: z.string().min(1, "Project code is required"),
  name: z.string().min(1, "Name is required"),
});
type CreateProjectValues = z.infer<typeof createProjectSchema>;

function CreateProjectForm({ onCreated }: { onCreated: () => void }) {
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateProjectValues>({
    resolver: zodResolver(createProjectSchema),
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    setSubmitting(true);
    try {
      // status/health/currency have server-side defaults (schemas.py), but
      // openapi-typescript still generates them as required fields — pass
      // the same defaults explicitly rather than fighting the generator.
      await createProject({
        ...values,
        status: "PLANNING",
        health: "ON_TRACK",
        currency: "USD",
      });
      onCreated();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Could not create project.",
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
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="project_code" className="text-sm font-medium">
            Project code
          </label>
          <input
            id="project_code"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("project_code")}
          />
          {errors.project_code ? (
            <p className="mt-1 text-sm text-destructive">
              {errors.project_code.message}
            </p>
          ) : null}
        </div>
        <div>
          <label htmlFor="name" className="text-sm font-medium">
            Name
          </label>
          <input
            id="name"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("name")}
          />
          {errors.name ? (
            <p className="mt-1 text-sm text-destructive">
              {errors.name.message}
            </p>
          ) : null}
        </div>
      </div>
      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <Button type="submit" disabled={submitting}>
        {submitting ? "Creating..." : "Create project"}
      </Button>
    </form>
  );
}

function ProjectTable({ projects }: { projects: Project[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Project</th>
            <th className="py-2 font-medium">Status</th>
            <th className="py-2 font-medium">Health</th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => (
            <tr key={project.id} className="border-b border-border">
              <td className="py-2">
                <Link
                  href={`/projects/${project.id}`}
                  className="font-medium hover:underline"
                >
                  {project.name}
                </Link>
                <div className="text-muted-foreground">
                  {project.project_code}
                </div>
              </td>
              <td className="py-2">
                <Badge>{project.status}</Badge>
              </td>
              <td className="py-2">
                <Badge>{project.health}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
