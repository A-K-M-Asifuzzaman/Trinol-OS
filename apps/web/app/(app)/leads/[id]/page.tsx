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
  archiveLead,
  convertLead,
  fetchLead,
  fetchLeadScore,
  scoreLead,
  updateLead,
  type LeadStage,
} from "@/lib/api/client";
import { useCanManageCrm } from "@/lib/role-context";

const STAGE_OPTIONS: LeadStage[] = [
  "NEW",
  "CONTACTED",
  "MEETING",
  "PROPOSAL",
  "NEGOTIATION",
  "WON",
  "LOST",
];

export default function LeadDetailPage() {
  const params = useParams<{ id: string }>();
  const leadId = params.id;
  const router = useRouter();
  const queryClient = useQueryClient();
  const canManage = useCanManageCrm();
  const [actionError, setActionError] = useState<string | null>(null);
  const [converting, setConverting] = useState(false);

  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["lead", leadId],
    queryFn: () => fetchLead(leadId),
  });

  async function handleStageChange(stage: LeadStage) {
    setActionError(null);
    try {
      await updateLead(leadId, { stage });
      queryClient.invalidateQueries({ queryKey: ["lead", leadId] });
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not update the lead.",
      );
    }
  }

  async function handleArchive() {
    setActionError(null);
    try {
      await archiveLead(leadId);
      queryClient.invalidateQueries({ queryKey: ["leads"] });
      router.push("/leads");
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not archive the lead.",
      );
    }
  }

  async function handleConvert() {
    setActionError(null);
    setConverting(true);
    try {
      const result = await convertLead(leadId);
      queryClient.invalidateQueries({ queryKey: ["leads"] });
      queryClient.invalidateQueries({ queryKey: ["clients"] });
      // The new project is the natural next stop — that's the whole point
      // of converting a lead (ROADMAP.md Phase 3 exit criteria).
      router.push(`/projects/${result.project.id}`);
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not convert this lead.",
      );
      setConverting(false);
    }
  }

  if (isLoading) return <ListLoadingState />;
  if (error || !data) {
    return (
      <ListErrorState
        message={
          error instanceof ApiError
            ? error.message
            : "Something went wrong loading this lead."
        }
        onRetry={() => refetch()}
      />
    );
  }

  const alreadyConverted = data.converted_client_id !== null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">{data.name}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {[data.email, data.phone].filter(Boolean).join(" · ")}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Badge>{data.source}</Badge>
        {data.estimated_value ? (
          <Badge>
            {data.estimated_value} {data.currency}
          </Badge>
        ) : null}
        <label htmlFor="stage" className="text-sm font-medium">
          Stage
        </label>
        <select
          id="stage"
          value={data.stage}
          onChange={(e) => handleStageChange(e.target.value as LeadStage)}
          disabled={!canManage}
          className="rounded border border-border px-2 py-1 text-sm disabled:opacity-50"
        >
          {STAGE_OPTIONS.map((stage) => (
            <option key={stage} value={stage}>
              {stage}
            </option>
          ))}
        </select>
      </div>
      {data.notes ? (
        <p className="text-sm text-muted-foreground">{data.notes}</p>
      ) : null}
      {actionError ? (
        <p role="alert" className="text-sm text-destructive">
          {actionError}
        </p>
      ) : null}
      {canManage ? (
        <div className="flex flex-wrap gap-2">
          {alreadyConverted ? (
            <p className="text-sm text-muted-foreground">
              Already converted to a client.
            </p>
          ) : (
            <Button onClick={handleConvert} disabled={converting}>
              {converting ? "Converting..." : "Convert to client"}
            </Button>
          )}
          <Button variant="outline" onClick={handleArchive}>
            Archive lead
          </Button>
        </div>
      ) : null}
      <LeadScorePanel leadId={leadId} canManage={canManage} />
    </div>
  );
}

function LeadScorePanel({
  leadId,
  canManage,
}: {
  leadId: string;
  canManage: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [scoring, setScoring] = useState(false);
  const score = useQuery({
    queryKey: ["lead-score", leadId],
    queryFn: () => fetchLeadScore(leadId),
    // A lead with no score yet 404s — the common case, not a transient
    // failure worth react-query's default retry backoff (the same
    // lesson Phase 7 Stage 3's stuck-loading-state bug already taught
    // this app about an *expected* non-200 response).
    retry: false,
  });

  async function handleScore() {
    setError(null);
    setScoring(true);
    try {
      await scoreLead(leadId);
      await score.refetch();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not score this lead.",
      );
    } finally {
      setScoring(false);
    }
  }

  return (
    <div className="rounded border border-border p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-muted-foreground">
          AI lead score
        </h3>
        {canManage ? (
          <Button variant="outline" onClick={handleScore} disabled={scoring}>
            {scoring ? "Scoring..." : score.data ? "Rescore" : "Score"}
          </Button>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {score.data ? (
        <div className="mt-2 space-y-1">
          <div className="flex items-center gap-2">
            <Badge>{score.data.score} / 100</Badge>
            {score.data.stale ? (
              <span className="text-xs text-muted-foreground">
                Lead has changed since this was computed.
              </span>
            ) : null}
          </div>
          <p className="text-sm">{score.data.rationale}</p>
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">Not scored yet.</p>
      )}
    </div>
  );
}
