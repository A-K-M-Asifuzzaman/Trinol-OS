import type { ReactNode } from "react";
import { AppShell } from "@/components/nav/app-shell";
import { fetchSessionInfo, type SessionInfo } from "@/lib/api/client";
import { getServerCookieHeader } from "@/lib/api/server-cookie";

// RBAC.md §2: Finance must be invisible to MEMBER/MANAGER, not just gated at
// the API — resolving the role here, server-side, is what lets Sidebar
// filter navigation by it (a role Sidebar can't see on its own).
//
// Also the fix for a real gap Stage 11's E2E smoke test surfaced: csrf_token
// (AUTH.md §6) only ever lived in an in-memory client variable set once,
// right after the login form's own completeSignIn() call — any full page
// load afterward (a hard refresh, a new tab, `page.goto()` in Playwright)
// wipes that in-memory value with nothing to restore it, so the very next
// POST/PATCH/DELETE from an already-authenticated session would 403 with
// "Invalid CSRF token". This layout wraps every authenticated page, so
// rehydrating it here (via AppShell, a client component) covers every case
// a fresh page load can happen, not just the login form's own.
async function getSessionInfo(): Promise<SessionInfo | null> {
  try {
    return await fetchSessionInfo(await getServerCookieHeader());
  } catch {
    return null;
  }
}

export default async function AppLayout({ children }: { children: ReactNode }) {
  const session = await getSessionInfo();
  return (
    <AppShell
      role={session?.role ?? null}
      csrfToken={session?.csrf_token ?? null}
    >
      {children}
    </AppShell>
  );
}
