"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  addMeetingParticipant,
  createMeetingAction,
  createMeetingDecision,
  deleteMeeting,
  deleteMeetingAction,
  deleteMeetingDecision,
  extractMeetingActions,
  fetchMeeting,
  fetchMeetingActions,
  fetchMeetingDecisions,
  fetchMeetingParticipants,
  fetchMeetingSummary,
  fetchTeamMembers,
  promoteMeetingAction,
  removeMeetingParticipant,
  summarizeMeeting,
  updateMeetingParticipantResponse,
  type Meeting,
  type MeetingAction,
  type MeetingDecision,
  type MeetingParticipant,
  type MeetingParticipantResponseUpdateRequest,
} from "@/lib/api/client";

// MASTER_PROMPT §14's five tabs. "Agenda" is presentational only — no
// backing field or table anywhere in DATABASE.md's meetings spec — so it
// just renders the meeting's own `description`, the closest fit, rather
// than querying anything. "Notes" renders the meeting's own `notes` field
// the same way. Neither has an edit UI this stage: the plan's own exit
// criteria (create meeting, add participant, add decision, add action,
// promote) never asked for one. `ponytail: read-only Agenda/Notes/meeting
// fields, add an edit form when requested.`
const TABS = [
  "Agenda",
  "Attendees",
  "Notes",
  "Decisions",
  "Action Items",
] as const;
type Tab = (typeof TABS)[number];

export default function MeetingDetailPage() {
  const params = useParams<{ id: string }>();
  const meetingId = params.id;
  const router = useRouter();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("Agenda");
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["meeting", meetingId],
    queryFn: () => fetchMeeting(meetingId),
  });

  // No client-side permission pre-check (RBAC.md §3's creator-or-MANAGER+
  // rule is a service-layer concern) — attempt the call, surface whatever
  // ApiError comes back, same pattern every other mutation in this app
  // already uses (e.g. projects/[id]/page.tsx's handleMoveTask).
  async function handleDeleteMeeting() {
    setActionError(null);
    try {
      await deleteMeeting(meetingId);
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
      router.push("/meetings");
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Could not delete this meeting.",
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
            : "Something went wrong loading this meeting."
        }
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold">{data.title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {new Date(data.starts_at).toLocaleString()} –{" "}
            {new Date(data.ends_at).toLocaleString()}
          </p>
          {data.location ? (
            <p className="text-sm text-muted-foreground">{data.location}</p>
          ) : null}
          {data.meeting_url ? (
            <a
              href={data.meeting_url}
              className="text-sm text-primary hover:underline"
            >
              Join link
            </a>
          ) : null}
        </div>
        <Button variant="outline" onClick={handleDeleteMeeting}>
          Delete meeting
        </Button>
      </div>
      <div className="flex flex-wrap gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            aria-current={tab === t}
            className={`rounded-t px-3 py-1.5 text-sm font-medium ${
              tab === t
                ? "border-b-2 border-primary text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "Agenda" ? <AgendaTab meeting={data} /> : null}
      {tab === "Attendees" ? <AttendeesTab meetingId={meetingId} /> : null}
      {tab === "Notes" ? <NotesTab meeting={data} /> : null}
      {tab === "Decisions" ? <DecisionsTab meetingId={meetingId} /> : null}
      {tab === "Action Items" ? <ActionItemsTab meetingId={meetingId} /> : null}
      {actionError ? (
        <p role="alert" className="text-sm text-destructive">
          {actionError}
        </p>
      ) : null}
    </div>
  );
}

function AgendaTab({ meeting }: { meeting: Meeting }) {
  if (!meeting.description) {
    return (
      <ListEmptyState
        title="No agenda yet"
        description="Add a description when editing this meeting."
      />
    );
  }
  return <p className="whitespace-pre-wrap text-sm">{meeting.description}</p>;
}

function NotesTab({ meeting }: { meeting: Meeting }) {
  return (
    <div className="space-y-6">
      {meeting.notes ? (
        <p className="whitespace-pre-wrap text-sm">{meeting.notes}</p>
      ) : (
        <ListEmptyState
          title="No notes yet"
          description="Add notes during or after the meeting."
        />
      )}
      <MeetingSummaryPanel meetingId={meeting.id} />
    </div>
  );
}

function MeetingSummaryPanel({ meetingId }: { meetingId: string }) {
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const summary = useQuery({
    queryKey: ["meeting-summary", meetingId],
    queryFn: () => fetchMeetingSummary(meetingId),
    // A meeting with no summary yet 404s — that's the common case, not a
    // transient failure worth react-query's default 3-retry backoff (the
    // same lesson Phase 7 Stage 3's stuck-loading-state bug already
    // taught this app about an *expected* non-200 response).
    retry: false,
  });

  async function handleGenerate() {
    setError(null);
    setGenerating(true);
    try {
      await summarizeMeeting(meetingId);
      await summary.refetch();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not summarize this meeting.",
      );
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="rounded border border-border p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-muted-foreground">
          AI summary
        </h3>
        <Button
          variant="outline"
          onClick={handleGenerate}
          disabled={generating}
        >
          {generating
            ? "Summarizing..."
            : summary.data
              ? "Regenerate summary"
              : "Summarize"}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {summary.data ? (
        <p className="mt-2 whitespace-pre-wrap text-sm">
          {summary.data.content}
        </p>
      ) : summary.isLoading ? (
        <p className="mt-2 text-sm text-muted-foreground">Loading...</p>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">
          Not summarized yet.
        </p>
      )}
    </div>
  );
}

function AttendeesTab({ meetingId }: { meetingId: string }) {
  const queryClient = useQueryClient();
  const [rowError, setRowError] = useState<string | null>(null);
  const [mode, setMode] = useState<"member" | "external">("member");
  const [memberId, setMemberId] = useState("");
  const [externalEmail, setExternalEmail] = useState("");

  const participants = useQuery({
    queryKey: ["meeting-participants", meetingId],
    queryFn: () => fetchMeetingParticipants(meetingId),
  });
  const members = useQuery({
    queryKey: ["team-members-for-attendees"],
    queryFn: () => fetchTeamMembers({ limit: 200 }),
  });

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    setRowError(null);
    try {
      await addMeetingParticipant(meetingId, {
        user_id: mode === "member" ? memberId || null : null,
        external_email: mode === "external" ? externalEmail || null : null,
      });
      setMemberId("");
      setExternalEmail("");
      queryClient.invalidateQueries({
        queryKey: ["meeting-participants", meetingId],
      });
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not add that participant.",
      );
    }
  }

  async function handleRemove(participantId: string) {
    setRowError(null);
    try {
      await removeMeetingParticipant(meetingId, participantId);
      queryClient.invalidateQueries({
        queryKey: ["meeting-participants", meetingId],
      });
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not remove that participant.",
      );
    }
  }

  async function handleRespond(
    participantId: string,
    response: MeetingParticipantResponseUpdateRequest["response"],
  ) {
    setRowError(null);
    try {
      await updateMeetingParticipantResponse(meetingId, participantId, {
        response,
      });
      queryClient.invalidateQueries({
        queryKey: ["meeting-participants", meetingId],
      });
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not update that response.",
      );
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleAdd} className="flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor="attendee-mode" className="text-sm font-medium">
            Invite
          </label>
          <select
            id="attendee-mode"
            value={mode}
            onChange={(e) => setMode(e.target.value as "member" | "external")}
            className="mt-1 rounded border border-border px-2 py-1.5 text-sm"
          >
            <option value="member">Team member</option>
            <option value="external">External guest</option>
          </select>
        </div>
        {mode === "member" ? (
          <div>
            <label htmlFor="attendee-member" className="text-sm font-medium">
              Member
            </label>
            <select
              id="attendee-member"
              value={memberId}
              onChange={(e) => setMemberId(e.target.value)}
              className="mt-1 rounded border border-border px-2 py-1.5 text-sm"
            >
              <option value="">Select...</option>
              {members.data?.items.map((member) => (
                <option key={member.user_id} value={member.user_id}>
                  {member.full_name} ({member.email})
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div>
            <label htmlFor="attendee-email" className="text-sm font-medium">
              Email
            </label>
            <input
              id="attendee-email"
              type="email"
              value={externalEmail}
              onChange={(e) => setExternalEmail(e.target.value)}
              className="mt-1 rounded border border-border px-3 py-1.5 text-sm"
            />
          </div>
        )}
        <Button type="submit">Add attendee</Button>
      </form>
      {rowError ? (
        <p role="alert" className="text-sm text-destructive">
          {rowError}
        </p>
      ) : null}
      {participants.isLoading ? (
        <ListLoadingState />
      ) : participants.error || !participants.data ? (
        <ListErrorState
          message="Something went wrong loading attendees."
          onRetry={() => participants.refetch()}
        />
      ) : participants.data.items.length === 0 ? (
        <ListEmptyState title="No attendees yet" />
      ) : (
        <ul className="space-y-2">
          {participants.data.items.map((participant: MeetingParticipant) => (
            <li
              key={participant.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded border border-border p-3 text-sm"
            >
              <span>{participant.external_email ?? participant.user_id}</span>
              <div className="flex items-center gap-2">
                <select
                  value={participant.response}
                  onChange={(e) =>
                    handleRespond(
                      participant.id,
                      e.target
                        .value as MeetingParticipantResponseUpdateRequest["response"],
                    )
                  }
                  className="rounded border border-border px-2 py-1 text-sm"
                >
                  <option value="PENDING">Pending</option>
                  <option value="ACCEPTED">Accepted</option>
                  <option value="DECLINED">Declined</option>
                  <option value="TENTATIVE">Tentative</option>
                </select>
                <Button
                  variant="outline"
                  onClick={() => handleRemove(participant.id)}
                >
                  Remove
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DecisionsTab({ meetingId }: { meetingId: string }) {
  const queryClient = useQueryClient();
  const [body, setBody] = useState("");
  const [rowError, setRowError] = useState<string | null>(null);
  const decisions = useQuery({
    queryKey: ["meeting-decisions", meetingId],
    queryFn: () => fetchMeetingDecisions(meetingId),
  });

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setRowError(null);
    try {
      await createMeetingDecision(meetingId, { body });
      setBody("");
      queryClient.invalidateQueries({
        queryKey: ["meeting-decisions", meetingId],
      });
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not record that decision.",
      );
    }
  }

  async function handleDelete(decisionId: string) {
    setRowError(null);
    try {
      await deleteMeetingDecision(meetingId, decisionId);
      queryClient.invalidateQueries({
        queryKey: ["meeting-decisions", meetingId],
      });
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not delete that decision.",
      );
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-2">
        <div className="flex-1">
          <label htmlFor="decision-body" className="text-sm font-medium">
            New decision
          </label>
          <input
            id="decision-body"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-1.5 text-sm"
          />
        </div>
        <Button type="submit">Record decision</Button>
      </form>
      {rowError ? (
        <p role="alert" className="text-sm text-destructive">
          {rowError}
        </p>
      ) : null}
      {decisions.isLoading ? (
        <ListLoadingState />
      ) : decisions.error || !decisions.data ? (
        <ListErrorState
          message="Something went wrong loading decisions."
          onRetry={() => decisions.refetch()}
        />
      ) : decisions.data.items.length === 0 ? (
        <ListEmptyState title="No decisions yet" />
      ) : (
        <ul className="space-y-2">
          {decisions.data.items.map((decision: MeetingDecision) => (
            <li
              key={decision.id}
              className="flex items-center justify-between gap-2 rounded border border-border p-3 text-sm"
            >
              <span>{decision.body}</span>
              <Button
                variant="outline"
                onClick={() => handleDelete(decision.id)}
              >
                Delete
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ActionItemsTab({ meetingId }: { meetingId: string }) {
  const queryClient = useQueryClient();
  const [description, setDescription] = useState("");
  const [rowError, setRowError] = useState<string | null>(null);
  const [promotingId, setPromotingId] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const actions = useQuery({
    queryKey: ["meeting-actions", meetingId],
    queryFn: () => fetchMeetingActions(meetingId),
  });

  async function handleExtract() {
    setRowError(null);
    setExtracting(true);
    try {
      await extractMeetingActions(meetingId);
      queryClient.invalidateQueries({
        queryKey: ["meeting-actions", meetingId],
      });
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not extract action items from this meeting.",
      );
    } finally {
      setExtracting(false);
    }
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setRowError(null);
    try {
      await createMeetingAction(meetingId, { description });
      setDescription("");
      queryClient.invalidateQueries({
        queryKey: ["meeting-actions", meetingId],
      });
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not add that action item.",
      );
    }
  }

  async function handleDelete(actionId: string) {
    setRowError(null);
    try {
      await deleteMeetingAction(meetingId, actionId);
      queryClient.invalidateQueries({
        queryKey: ["meeting-actions", meetingId],
      });
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not delete that action item.",
      );
    }
  }

  async function handlePromote(actionId: string) {
    setRowError(null);
    setPromotingId(actionId);
    try {
      await promoteMeetingAction(meetingId, actionId);
      queryClient.invalidateQueries({
        queryKey: ["meeting-actions", meetingId],
      });
    } catch (err) {
      setRowError(
        err instanceof ApiError
          ? err.message
          : "Could not promote that action item.",
      );
    } finally {
      setPromotingId(null);
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-2">
        <div className="flex-1">
          <label htmlFor="action-description" className="text-sm font-medium">
            New action item
          </label>
          <input
            id="action-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-1.5 text-sm"
          />
        </div>
        <Button type="submit">Add action item</Button>
        <Button
          type="button"
          variant="outline"
          onClick={handleExtract}
          disabled={extracting}
        >
          {extracting ? "Extracting..." : "Extract actions"}
        </Button>
      </form>
      {rowError ? (
        <p role="alert" className="text-sm text-destructive">
          {rowError}
        </p>
      ) : null}
      {actions.isLoading ? (
        <ListLoadingState />
      ) : actions.error || !actions.data ? (
        <ListErrorState
          message="Something went wrong loading action items."
          onRetry={() => actions.refetch()}
        />
      ) : actions.data.items.length === 0 ? (
        <ListEmptyState title="No action items yet" />
      ) : (
        <ul className="space-y-2">
          {actions.data.items.map((action: MeetingAction) => (
            <li
              key={action.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded border border-border p-3 text-sm"
            >
              <span>
                {action.description}
                {action.source === "AI" ? (
                  <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                    AI
                  </span>
                ) : null}
              </span>
              <div className="flex items-center gap-2">
                {action.task_id ? (
                  <Link
                    href={`/tasks/${action.task_id}`}
                    className="text-primary hover:underline"
                  >
                    View task
                  </Link>
                ) : (
                  <Button
                    variant="outline"
                    onClick={() => handlePromote(action.id)}
                    disabled={promotingId === action.id}
                  >
                    {promotingId === action.id
                      ? "Promoting..."
                      : "Promote to task"}
                  </Button>
                )}
                <Button
                  variant="outline"
                  onClick={() => handleDelete(action.id)}
                >
                  Delete
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
