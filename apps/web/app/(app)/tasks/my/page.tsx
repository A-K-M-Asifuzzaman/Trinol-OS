import { ListErrorState } from "@/components/list/error-state";
import { TaskListView } from "@/components/tasks/task-list";
import { fetchSessionInfo } from "@/lib/api/client";
import { getServerCookieHeader } from "@/lib/api/server-cookie";

// ROADMAP.md Phase 2 decision 5: "mine" is resolved here, server-side, from
// the caller's own session — never a client-supplied assignee_id=me
// sentinel. Same backend GET /api/v1/tasks endpoint the plain /tasks page
// uses, just with the real membership user id already filled in.
export default async function MyTasksPage() {
  try {
    const session = await fetchSessionInfo(await getServerCookieHeader());
    return <TaskListView title="My Work" assigneeId={session.user_id} />;
  } catch {
    return (
      <ListErrorState message="Could not determine your session. Try signing in again." />
    );
  }
}
