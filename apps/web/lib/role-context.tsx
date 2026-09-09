"use client";

import { createContext, useContext, type ReactNode } from "react";

// RBAC.md §2: leads/clients/pipeline are role-threshold only (no
// ownership-split rule this phase, unlike Projects/Tasks) — MANAGER+ can
// create/edit/convert, MEMBER is view-only. Phase 2's pages never needed
// this: their real authorization rule is resource-specific (ownership/
// membership), so a simple role check in the UI would have been wrong
// there. AppShell already resolves `role` server-side for Sidebar
// (layout.tsx) — this just makes that same value reachable from page
// content too, via context instead of prop-drilling through every route.
const RoleContext = createContext<string | null>(null);

export function RoleProvider({
  role,
  children,
}: {
  role: string | null;
  children: ReactNode;
}) {
  return <RoleContext.Provider value={role}>{children}</RoleContext.Provider>;
}

export function useRole(): string | null {
  return useContext(RoleContext);
}

const MANAGER_PLUS_ROLES = new Set(["MANAGER", "ADMIN", "OWNER"]);

/** Whether the current viewer can create/edit/convert leads and clients. */
export function useCanManageCrm(): boolean {
  const role = useRole();
  return role !== null && MANAGER_PLUS_ROLES.has(role);
}
