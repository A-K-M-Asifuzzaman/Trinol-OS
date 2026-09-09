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
  createLead,
  fetchLeads,
  type Lead,
  type LeadSource,
} from "@/lib/api/client";
import { useCanManageCrm } from "@/lib/role-context";

const SOURCE_OPTIONS: LeadSource[] = [
  "WEBSITE",
  "FACEBOOK",
  "LINKEDIN",
  "REFERRAL",
  "EMAIL",
  "PHONE",
  "OTHER",
];

// Same client-rendered/four-state pattern as Projects/Tasks (Phase 2 Stage
// 8) — see Team's own comment for why this departs from ARCHITECTURE.md
// §5's server-rendered default.
export default function LeadsPage() {
  const queryClient = useQueryClient();
  const canManage = useCanManageCrm();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["leads"],
    queryFn: () => fetchLeads({ limit: 50, offset: 0 }),
  });
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Leads</h1>
        {canManage ? (
          <Button onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "New lead"}
          </Button>
        ) : null}
      </div>
      {showForm && canManage ? (
        <CreateLeadForm
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["leads"] });
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
              : "Something went wrong loading leads."
          }
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <ListEmptyState
          title="No leads yet"
          description="Create one to get started."
        />
      ) : (
        <LeadTable leads={data.items} />
      )}
    </div>
  );
}

const createLeadSchema = z
  .object({
    name: z.string().min(1, "Name is required"),
    email: z.string().optional(),
    phone: z.string().optional(),
    source: z.enum(SOURCE_OPTIONS as [LeadSource, ...LeadSource[]]),
  })
  // Mirrors ck_lead_contact (DATABASE.md §3) client-side for faster
  // feedback — the API still re-validates and is the real control
  // (ARCHITECTURE.md §5).
  .refine((values) => values.email || values.phone, {
    message: "Email or phone is required",
    path: ["email"],
  });
type CreateLeadValues = z.infer<typeof createLeadSchema>;

function CreateLeadForm({ onCreated }: { onCreated: () => void }) {
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateLeadValues>({ resolver: zodResolver(createLeadSchema) });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    setSubmitting(true);
    try {
      // currency/stage have server-side defaults (schemas.py), but
      // openapi-typescript still generates them as required fields — pass
      // the same defaults explicitly rather than fighting the generator.
      await createLead({
        name: values.name,
        email: values.email || null,
        phone: values.phone || null,
        source: values.source,
        currency: "USD",
        stage: "NEW",
      });
      onCreated();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Could not create lead.",
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
        <div>
          <label htmlFor="source" className="text-sm font-medium">
            Source
          </label>
          <select
            id="source"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            defaultValue="WEBSITE"
            {...register("source")}
          >
            {SOURCE_OPTIONS.map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="email" className="text-sm font-medium">
            Email
          </label>
          <input
            id="email"
            type="email"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("email")}
          />
        </div>
        <div>
          <label htmlFor="phone" className="text-sm font-medium">
            Phone
          </label>
          <input
            id="phone"
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
            {...register("phone")}
          />
        </div>
      </div>
      {errors.email ? (
        <p className="text-sm text-destructive">{errors.email.message}</p>
      ) : null}
      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <Button type="submit" disabled={submitting}>
        {submitting ? "Creating..." : "Create lead"}
      </Button>
    </form>
  );
}

function LeadTable({ leads }: { leads: Lead[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Lead</th>
            <th className="py-2 font-medium">Stage</th>
            <th className="py-2 font-medium">Source</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => (
            <tr key={lead.id} className="border-b border-border">
              <td className="py-2">
                <Link
                  href={`/leads/${lead.id}`}
                  className="font-medium hover:underline"
                >
                  {lead.name}
                </Link>
                <div className="text-muted-foreground">
                  {lead.email ?? lead.phone}
                </div>
              </td>
              <td className="py-2">
                <Badge>{lead.stage}</Badge>
              </td>
              <td className="py-2">
                <Badge>{lead.source}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
