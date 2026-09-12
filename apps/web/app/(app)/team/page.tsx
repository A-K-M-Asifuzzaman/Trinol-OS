"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { ListEmptyState } from "@/components/list/empty-state";
import { ListErrorState } from "@/components/list/error-state";
import { ListLoadingState } from "@/components/list/loading-state";
import { ApiError, fetchTeamMembers, type Membership } from "@/lib/api/client";

// Deliberately client-rendered (a departure from ARCHITECTURE.md §5's
// server-rendered-by-default lists): Stage 10's proof criterion is that all
// four list states are unit-testable against MSW, which needs a client-side
// fetch. The dashboard's team-count tile stays server-rendered per decision
// 8 — this is the one list that needs its states exercised directly.
export default function TeamPage() {
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["team-members"],
    queryFn: () => fetchTeamMembers({ limit: 50, offset: 0 }),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Team</h1>
      {isLoading ? (
        <ListLoadingState />
      ) : error ? (
        <ListErrorState
          message={
            error instanceof ApiError
              ? error.message
              : "Something went wrong loading the team."
          }
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <ListEmptyState
          title="No team members yet"
          description="Invite someone to get started."
        />
      ) : (
        <TeamTable members={data.items} />
      )}
    </div>
  );
}

function TeamTable({ members }: { members: Membership[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 font-medium">Name</th>
            <th className="py-2 font-medium">Role</th>
            <th className="py-2 font-medium">Job title</th>
            <th className="py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {members.map((member) => (
            <tr key={member.id} className="border-b border-border">
              <td className="py-2">
                <div className="font-medium">{member.full_name}</div>
                <div className="text-muted-foreground">{member.email}</div>
              </td>
              <td className="py-2">
                <Badge>{member.role}</Badge>
              </td>
              <td className="py-2">{member.job_title ?? "—"}</td>
              <td className="py-2">{member.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
