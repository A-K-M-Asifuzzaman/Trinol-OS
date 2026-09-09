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
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">{data.name}</h1>
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
    </div>
  );
}
