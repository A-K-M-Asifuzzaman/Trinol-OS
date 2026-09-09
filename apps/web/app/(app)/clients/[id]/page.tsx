"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  archiveClient,
  fetchClient,
  fetchProjects,
  type Client,
} from "@/lib/api/client";
import { useCanManageCrm } from "@/lib/role-context";

// Phase 4/5 entities (invoices, payments, meetings, documents) don't exist
// yet — those tabs are present but empty-state-only, per this stage's own
// exit criteria, rather than left off the page entirely (so the page's
// eventual shape is visible now instead of a surprise later).
const TABS = [
  "Overview",
  "Projects",
  "Invoices",
  "Payments",
  "Meetings",
  "Documents",
  "Activity",
] as const;
type Tab = (typeof TABS)[number];

export default function ClientDetailPage() {
  const params = useParams<{ id: string }>();
  const clientId = params.id;
  const router = useRouter();
  const queryClient = useQueryClient();
  const canManage = useCanManageCrm();
  const [tab, setTab] = useState<Tab>("Overview");
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["client", clientId],
    queryFn: () => fetchClient(clientId),
  });

  async function handleArchive() {
    setActionError(null);
    try {
      await archiveClient(clientId);
      queryClient.invalidateQueries({ queryKey: ["clients"] });
      router.push("/clients");
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not archive the client.",
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
            : "Something went wrong loading this client."
        }
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{data.name}</h1>
          {data.company ? (
            <p className="text-sm text-muted-foreground">{data.company}</p>
          ) : null}
        </div>
        <Badge>{data.status}</Badge>
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
      {tab === "Overview" ? <OverviewTab client={data} /> : null}
      {tab === "Projects" ? <ProjectsTab clientId={clientId} /> : null}
      {tab === "Invoices" ? (
        <ListEmptyState
          title="No invoices yet"
          description="Invoicing arrives in a later phase."
        />
      ) : null}
      {tab === "Payments" ? (
        <ListEmptyState
          title="No payments yet"
          description="Payments arrive in a later phase."
        />
      ) : null}
      {tab === "Meetings" ? (
        <ListEmptyState
          title="No meetings yet"
          description="Meetings arrive in a later phase."
        />
      ) : null}
      {tab === "Documents" ? (
        <ListEmptyState
          title="No documents yet"
          description="Document references arrive in a later phase."
        />
      ) : null}
      {tab === "Activity" ? (
        <ListEmptyState
          title="No activity yet"
          description="A client-scoped activity view arrives in a later phase."
        />
      ) : null}
      {actionError ? (
        <p role="alert" className="text-sm text-destructive">
          {actionError}
        </p>
      ) : null}
      {canManage ? (
        <Button variant="outline" onClick={handleArchive}>
          Archive client
        </Button>
      ) : null}
    </div>
  );
}

function OverviewTab({ client }: { client: Client }) {
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-2">
      <Field label="Email" value={client.email} />
      <Field label="Phone" value={client.phone} />
      <Field label="Website" value={client.website} />
      <Field label="Address" value={client.address} />
      {client.notes ? (
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground">Notes</dt>
          <dd className="mt-1">{client.notes}</dd>
        </div>
      ) : null}
    </dl>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="mt-1">{value}</dd>
    </div>
  );
}

function ProjectsTab({ clientId }: { clientId: string }) {
  // ponytail: no server-side client_id filter exists on GET /projects yet
  // (it never needed one before this stage) — fetch a generously-capped
  // list and filter here, same bounded-list-for-a-picker shape
  // task-list.tsx's own project picker already uses. Add a real query
  // param if this client's real usage ever approaches the cap.
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["projects-for-client-tab"],
    queryFn: () => fetchProjects({ limit: 200 }),
  });

  if (isLoading) return <ListLoadingState />;
  if (error || !data) {
    return (
      <ListErrorState
        message={
          error instanceof ApiError
            ? error.message
            : "Something went wrong loading projects."
        }
        onRetry={() => refetch()}
      />
    );
  }

  const projects = data.items.filter(
    (project) => project.client_id === clientId,
  );
  if (projects.length === 0) {
    return (
      <ListEmptyState
        title="No projects yet"
        description="Convert a lead or link a project to this client."
      />
    );
  }

  return (
    <ul className="space-y-2">
      {projects.map((project) => (
        <li
          key={project.id}
          className="rounded border border-border p-3 text-sm"
        >
          <Link
            href={`/projects/${project.id}`}
            className="font-medium hover:underline"
          >
            {project.name}
          </Link>
          <div className="mt-1 flex gap-2">
            <Badge>{project.status}</Badge>
            <Badge>{project.health}</Badge>
          </div>
        </li>
      ))}
    </ul>
  );
}
