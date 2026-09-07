import type { ReactNode } from "react";
import { AppShell } from "@/components/nav/app-shell";
import { fetchSessionInfo } from "@/lib/api/client";
import { getServerCookieHeader } from "@/lib/api/server-cookie";

// RBAC.md §2: Finance must be invisible to MEMBER/MANAGER, not just gated at
// the API — resolving the role here, server-side, is what lets Sidebar
// filter navigation by it (a role Sidebar can't see on its own).
async function getRole(): Promise<string | null> {
  try {
    const info = await fetchSessionInfo(await getServerCookieHeader());
    return info.role;
  } catch {
    return null;
  }
}

export default async function AppLayout({ children }: { children: ReactNode }) {
  const role = await getRole();
  return <AppShell role={role}>{children}</AppShell>;
}
