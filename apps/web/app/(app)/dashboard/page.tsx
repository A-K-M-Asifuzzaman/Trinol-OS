import { fetchProjects, fetchTasks, fetchTeamMembers } from "@/lib/api/client";
import { getServerCookieHeader } from "@/lib/api/server-cookie";

// ARCHITECTURE.md §5: lists/pages are server-rendered by default — the
// server component calls the API with the incoming cookie. Phase 1 plan
// decision 8: every widget ships as an empty-state shell until its own data
// exists; Phase 2 Stage 8 fills in tasks/projects, replacing those two
// placeholders.
async function getCount(
  fetcher: (options: { limit: number; cookie: string }) => Promise<{ total: number }>,
): Promise<number | null> {
  try {
    const result = await fetcher({ limit: 1, cookie: await getServerCookieHeader() });
    return result.total;
  } catch {
    return null;
  }
}

export default async function DashboardPage() {
  const [teamCount, taskCount, projectCount] = await Promise.all([
    getCount(fetchTeamMembers),
    // `ponytail: total task/project count, not "open"/"active" only — the
    // list endpoints have no status filter for projects and only a single
    // equality filter for tasks, so a true "open" count needs either a
    // dedicated count endpoint or several requests; add when a real report
    // needs it` (MASTER_PROMPT §21's own "Recent activity" widget is the
    // richer version of this, already built in Stage 7).
    getCount(fetchTasks),
    getCount(fetchProjects),
  ]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <DashboardTile
          label="Team members"
          value={teamCount === null ? "—" : String(teamCount)}
        />
        <DashboardTile
          label="Open tasks"
          value={taskCount === null ? "—" : String(taskCount)}
        />
        <DashboardTile
          label="Active projects"
          value={projectCount === null ? "—" : String(projectCount)}
        />
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
