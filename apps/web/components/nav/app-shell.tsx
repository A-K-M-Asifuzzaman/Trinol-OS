"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Sidebar } from "@/components/nav/sidebar";
import { setCsrfToken } from "@/lib/api/client";
import { RoleProvider } from "@/lib/role-context";

// MASTER_PROMPT §32 / AGENTS.md's "a feature is not done until ... responsive
// behavior works": the sidebar can't permanently reserve a fixed-width
// column on a phone-sized viewport. Below md, it starts collapsed behind a
// toggle; at md and above it's always visible, same as before.
export function AppShell({
  role,
  csrfToken,
  children,
}: {
  role: string | null;
  csrfToken: string | null;
  children: React.ReactNode;
}) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // Rehydrates the in-memory CSRF token (AUTH.md §6) on every fresh page
  // load of an already-authenticated session — see layout.tsx's own comment
  // for why this can't just be the login form's job alone.
  useEffect(() => {
    if (csrfToken) setCsrfToken(csrfToken);
  }, [csrfToken]);

  return (
    <RoleProvider role={role}>
      <div className="flex min-h-screen flex-col md:flex-row">
        <header className="flex items-center justify-between border-b border-border p-4 md:hidden">
          <span className="text-sm font-semibold">Trinol OS</span>
          <Button
            type="button"
            variant="outline"
            aria-expanded={mobileNavOpen}
            aria-controls="app-sidebar"
            onClick={() => setMobileNavOpen((open) => !open)}
          >
            {mobileNavOpen ? "Close menu" : "Menu"}
          </Button>
        </header>
        <div
          id="app-sidebar"
          className={mobileNavOpen ? "block" : "hidden md:block"}
        >
          <Sidebar role={role} />
        </div>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </RoleProvider>
  );
}
