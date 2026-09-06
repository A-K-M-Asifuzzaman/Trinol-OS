import { cookies } from "next/headers";
import { fetchTeamMembers } from "@/lib/api/client";

// ARCHITECTURE.md §5: lists/pages are server-rendered by default — the
// server component calls the API with the incoming cookie. Phase 1 plan
// decision 8: every widget ships as an empty-state shell except the team-
// count tile, which is the only data that exists yet (GET /memberships).
async function getTeamCount(): Promise<number | null> {
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((cookie) => `${cookie.name}=${cookie.value}`)
      .join("; ");
    const result = await fetchTeamMembers({ limit: 1, cookie: cookieHeader });
    return result.total;
  } catch {
    return null;
  }
}

export default async function DashboardPage() {
  const teamCount = await getTeamCount();

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <DashboardTile
          label="Team members"
          value={teamCount === null ? "—" : String(teamCount)}
        />
        <DashboardTile label="Open tasks" value="—" placeholder />
        <DashboardTile label="Active projects" value="—" placeholder />
        <DashboardTile label="Open leads" value="—" placeholder />
      </div>
    </div>
  );
}

function DashboardTile({
  label,
  value,
  placeholder,
}: {
  label: string;
  value: string;
  placeholder?: boolean;
}) {
  return (
    <div className="rounded border border-border p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p
        className={`mt-1 text-2xl font-semibold ${placeholder ? "text-muted-foreground" : ""}`}
      >
        {value}
      </p>
    </div>
  );
}
