"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  createMeeting,
  fetchMeetings,
  type Meeting,
} from "@/lib/api/client";

// Same client-rendered/four-state pattern as Leads/Clients (Phase 3 Stage
// 8) — see Team's own comment for why this departs from ARCHITECTURE.md
// §5's server-rendered default. RBAC.md §2: "Meetings: create/edit own" is
// granted to every role — unlike Leads/Clients, there's no MANAGER+ gate on
// the "New meeting" control here.
export default function MeetingsPage() {
  const queryClient = useQueryClient();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["meetings"],
    queryFn: () => fetchMeetings({ limit: 50, offset: 0 }),
  });
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Meetings</h1>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "New meeting"}
        </Button>
      </div>
      {showForm ? (
        <CreateMeetingForm
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["meetings"] });
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
              : "Something went wrong loading meetings."
          }
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <ListEmptyState
          title="No meetings yet"
          description="Create one to get started."
        />
      ) : (
        <MeetingTable meetings={data.items} />
      )}
    </div>
  );
}

const createMeetingSchema = z
  .object({
    title: z.string().min(1, "Title is required"),
    starts_at: z.string().min(1, "Start time is required"),
    ends_at: z.string().min(1, "End time is required"),
  })
  // Mirrors ck_meeting_times (DATABASE.md §3) client-side for faster
  // feedback — the API still re-validates and is the real control
  // (ARCHITECTURE.md §5).
  .refine((values) => new Date(values.ends_at) > new Date(values.starts_at), {
    message: "End time must be after the start time",
    path: ["ends_at"],
  });
type CreateMeetingValues = z.infer<typeof createMeetingSchema>;

function CreateMeetingForm({ onCreated }: { onCreated: () => void }) {
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateMeetingValues>({
    resolver: zodResolver(createMeetingSchema),
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    setSubmitting(true);
    try {
      // datetime-local inputs give local-time strings with no offset;
      // new Date(...).toISOString() is the standard way to normalize that
      // to a real UTC instant before sending it to the API.
      await createMeeting({
        title: values.title,
        starts_at: new Date(values.starts_at).toISOString(),
        ends_at: new Date(values.ends_at).toISOString(),
      });
      onCreated();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Could not create meeting.",
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
        <div className="sm:col-span-2">
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
          <label htmlFor="starts_at" className="text-sm font-medium">
            Starts
          </label>
          <input
            id="starts_at"
            type="datetime-local"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("starts_at")}
          />
          {errors.starts_at ? (
            <p className="mt-1 text-sm text-destructive">
              {errors.starts_at.message}
            </p>
          ) : null}
        </div>
        <div>
          <label htmlFor="ends_at" className="text-sm font-medium">
            Ends
          </label>
          <input
            id="ends_at"
            type="datetime-local"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("ends_at")}
          />
          {errors.ends_at ? (
            <p className="mt-1 text-sm text-destructive">
              {errors.ends_at.message}
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
        {submitting ? "Creating..." : "Create meeting"}
      </Button>
    </form>
  );
}

function MeetingTable({ meetings }: { meetings: Meeting[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Meeting</th>
            <th className="py-2 font-medium">Starts</th>
            <th className="py-2 font-medium">Ends</th>
          </tr>
        </thead>
        <tbody>
          {meetings.map((meeting) => (
            <tr key={meeting.id} className="border-b border-border">
              <td className="py-2">
                <Link
                  href={`/meetings/${meeting.id}`}
                  className="font-medium hover:underline"
                >
                  {meeting.title}
                </Link>
                {meeting.location ? (
                  <div className="text-muted-foreground">
                    {meeting.location}
                  </div>
                ) : null}
              </td>
              <td className="py-2">
                {new Date(meeting.starts_at).toLocaleString()}
              </td>
              <td className="py-2">
                {new Date(meeting.ends_at).toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
