"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import {
  ApiError,
  createDocument,
  deleteDocument,
  fetchClients,
  fetchDocuments,
  fetchMeetings,
  fetchProjects,
  type DocumentKind,
  type DocumentReference,
} from "@/lib/api/client";

const KIND_OPTIONS: DocumentKind[] = ["GOOGLE_DRIVE", "GITHUB", "OTHER"];
const KIND_LABELS: Record<DocumentKind, string> = {
  GOOGLE_DRIVE: "Google Drive",
  GITHUB: "GitHub",
  OTHER: "Other",
};

type LinkType = "none" | "project" | "client" | "meeting";

// Same client-rendered/four-state pattern as Leads/Meetings/Finance income
// (no client-side permission pre-check — DOCUMENT_WRITE is MANAGER+, but
// "New document"/edit/delete simply attempt the call and surface whatever
// ApiError comes back, matching Finance's own frontend stage rather than
// CRM's earlier useCanManageCrm()-hiding precedent).
export default function DocumentsPage() {
  const queryClient = useQueryClient();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["documents"],
    queryFn: () => fetchDocuments({ limit: 50, offset: 0 }),
  });
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Documents</h1>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "New document"}
        </Button>
      </div>
      {showForm ? (
        <CreateDocumentForm
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["documents"] });
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
              : "Something went wrong loading documents."
          }
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <ListEmptyState
          title="No documents yet"
          description="Add a link to get started."
        />
      ) : (
        <DocumentTable
          documents={data.items}
          onDeleted={() =>
            queryClient.invalidateQueries({ queryKey: ["documents"] })
          }
        />
      )}
    </div>
  );
}

function CreateDocumentForm({ onCreated }: { onCreated: () => void }) {
  const projects = useQuery({
    queryKey: ["projects-for-document"],
    queryFn: () => fetchProjects({ limit: 200 }),
  });
  const clients = useQuery({
    queryKey: ["clients-for-document"],
    queryFn: () => fetchClients({ limit: 200 }),
  });
  const meetings = useQuery({
    queryKey: ["meetings-for-document"],
    queryFn: () => fetchMeetings({ limit: 200 }),
  });

  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState<DocumentKind>("OTHER");
  // Phase 6 plan decision 4's own UI simplification: the schema allows more
  // than one parent at once, but the form only ever lets a user pick one —
  // a usability choice, not an API restriction.
  const [linkType, setLinkType] = useState<LinkType>("none");
  const [linkTargetId, setLinkTargetId] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const targets =
    linkType === "project"
      ? (projects.data?.items ?? []).map((p) => ({ id: p.id, label: p.name }))
      : linkType === "client"
        ? (clients.data?.items ?? []).map((c) => ({ id: c.id, label: c.name }))
        : linkType === "meeting"
          ? (meetings.data?.items ?? []).map((m) => ({
              id: m.id,
              label: m.title,
            }))
          : [];

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      await createDocument({
        title,
        url,
        kind,
        project_id:
          linkType === "project" && linkTargetId ? linkTargetId : null,
        client_id: linkType === "client" && linkTargetId ? linkTargetId : null,
        meeting_id:
          linkType === "meeting" && linkTargetId ? linkTargetId : null,
      });
      onCreated();
    } catch (err) {
      setFormError(
        err instanceof ApiError
          ? err.message
          : "Could not create that document.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-3 rounded border border-border p-4"
      noValidate
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="document-title" className="text-sm font-medium">
            Title
          </label>
          <input
            id="document-title"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label htmlFor="document-url" className="text-sm font-medium">
            URL
          </label>
          <input
            id="document-url"
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label htmlFor="document-kind" className="text-sm font-medium">
            Kind
          </label>
          <select
            id="document-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as DocumentKind)}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          >
            {KIND_OPTIONS.map((k) => (
              <option key={k} value={k}>
                {KIND_LABELS[k]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="document-link-type" className="text-sm font-medium">
            Link to
          </label>
          <select
            id="document-link-type"
            value={linkType}
            onChange={(e) => {
              setLinkType(e.target.value as LinkType);
              setLinkTargetId("");
            }}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          >
            <option value="none">None</option>
            <option value="project">Project</option>
            <option value="client">Client</option>
            <option value="meeting">Meeting</option>
          </select>
        </div>
        {linkType !== "none" ? (
          <div>
            <label
              htmlFor="document-link-target"
              className="text-sm font-medium"
            >
              {linkType === "project"
                ? "Project"
                : linkType === "client"
                  ? "Client"
                  : "Meeting"}
            </label>
            <select
              id="document-link-target"
              value={linkTargetId}
              onChange={(e) => setLinkTargetId(e.target.value)}
              className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            >
              <option value="">Select...</option>
              {targets.map((target) => (
                <option key={target.id} value={target.id}>
                  {target.label}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>
      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <Button type="submit" disabled={submitting}>
        {submitting ? "Creating..." : "Create document"}
      </Button>
    </form>
  );
}

function DocumentTable({
  documents,
  onDeleted,
}: {
  documents: DocumentReference[];
  onDeleted: () => void;
}) {
  const projects = useQuery({
    queryKey: ["projects-for-document-list"],
    queryFn: () => fetchProjects({ limit: 200 }),
  });
  const clients = useQuery({
    queryKey: ["clients-for-document-list"],
    queryFn: () => fetchClients({ limit: 200 }),
  });
  const meetings = useQuery({
    queryKey: ["meetings-for-document-list"],
    queryFn: () => fetchMeetings({ limit: 200 }),
  });
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function linkedName(document: DocumentReference): string | null {
    if (document.project_id) {
      return (
        projects.data?.items.find((p) => p.id === document.project_id)?.name ??
        null
      );
    }
    if (document.client_id) {
      return (
        clients.data?.items.find((c) => c.id === document.client_id)?.name ??
        null
      );
    }
    if (document.meeting_id) {
      return (
        meetings.data?.items.find((m) => m.id === document.meeting_id)?.title ??
        null
      );
    }
    return null;
  }

  async function handleDelete(documentId: string) {
    setDeleteError(null);
    try {
      await deleteDocument(documentId);
      onDeleted();
    } catch (err) {
      setDeleteError(
        err instanceof ApiError
          ? err.message
          : "Could not delete that document.",
      );
    }
  }

  return (
    <div className="space-y-2">
      {deleteError ? (
        <p role="alert" className="text-sm text-destructive">
          {deleteError}
        </p>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-2 font-medium">Title</th>
              <th className="py-2 font-medium">Kind</th>
              <th className="py-2 font-medium">Linked to</th>
              <th className="py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr key={document.id} className="border-b border-border">
                <td className="py-2">
                  <a
                    href={document.url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium hover:underline"
                  >
                    {document.title}
                  </a>
                </td>
                <td className="py-2">
                  <Badge>{KIND_LABELS[document.kind]}</Badge>
                </td>
                <td className="py-2">{linkedName(document) ?? "—"}</td>
                <td className="py-2 text-right">
                  <Button
                    variant="outline"
                    onClick={() => handleDelete(document.id)}
                  >
                    Delete
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
