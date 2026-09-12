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
  createClient,
  fetchClients,
  type Client,
} from "@/lib/api/client";
import { useCanManageCrm } from "@/lib/role-context";

// Same client-rendered/four-state pattern as Leads/Projects/Tasks.
export default function ClientsPage() {
  const queryClient = useQueryClient();
  const canManage = useCanManageCrm();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["clients"],
    queryFn: () => fetchClients({ limit: 50, offset: 0 }),
  });
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Clients</h1>
        {canManage ? (
          <Button onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "New client"}
          </Button>
        ) : null}
      </div>
      {showForm && canManage ? (
        <CreateClientForm
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["clients"] });
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
              : "Something went wrong loading clients."
          }
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <ListEmptyState
          title="No clients yet"
          description="Convert a lead or create one directly."
        />
      ) : (
        <ClientTable clients={data.items} />
      )}
    </div>
  );
}

const createClientSchema = z.object({
  name: z.string().min(1, "Name is required"),
  email: z.string().optional(),
  phone: z.string().optional(),
});
type CreateClientValues = z.infer<typeof createClientSchema>;

function CreateClientForm({ onCreated }: { onCreated: () => void }) {
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateClientValues>({
    resolver: zodResolver(createClientSchema),
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    setSubmitting(true);
    try {
      // status has a server-side default (schemas.py), but
      // openapi-typescript still generates it as a required field — pass
      // the same default explicitly rather than fighting the generator.
      await createClient({
        name: values.name,
        email: values.email || null,
        phone: values.phone || null,
        status: "ACTIVE",
      });
      onCreated();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Could not create client.",
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
      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <Button type="submit" disabled={submitting}>
        {submitting ? "Creating..." : "Create client"}
      </Button>
    </form>
  );
}

function ClientTable({ clients }: { clients: Client[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Client</th>
            <th className="py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {clients.map((client) => (
            <tr key={client.id} className="border-b border-border">
              <td className="py-2">
                <Link
                  href={`/clients/${client.id}`}
                  className="font-medium hover:underline"
                >
                  {client.name}
                </Link>
                <div className="text-muted-foreground">
                  {client.email ?? client.phone}
                </div>
              </td>
              <td className="py-2">
                <Badge>{client.status}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
