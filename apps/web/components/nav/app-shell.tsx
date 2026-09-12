"use client";

import { usePathname } from "next/navigation";
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
  const pathname = usePathname();

  // Rehydrates the in-memory CSRF token (AUTH.md §6) on every fresh page
  // load of an already-authenticated session — see layout.tsx's own comment
  // for why this can't just be the login form's job alone.
  useEffect(() => {
    if (csrfToken) setCsrfToken(csrfToken);
  }, [csrfToken]);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  return (
    <RoleProvider role={role}>
      <div className="flex min-h-screen bg-[#111214]">
        <header className="fixed inset-x-0 top-0 z-40 flex h-16 items-center justify-between border-b border-white/10 bg-[#111214] px-4 text-white md:hidden">
          <span className="flex items-center gap-2 text-sm font-bold">
            <span className="h-2 w-2 rounded-full bg-[hsl(var(--signal))]" />
            Trinol OS
          </span>
          <Button
            type="button"
            variant="ghost"
            className="text-white hover:bg-white/10"
            aria-expanded={mobileNavOpen}
            aria-controls="app-sidebar"
            onClick={() => setMobileNavOpen((open) => !open)}
          >
            {mobileNavOpen ? "Close menu" : "Menu"}
          </Button>
        </header>
        {mobileNavOpen ? (
          <button
            type="button"
            aria-label="Close navigation"
            className="fixed inset-0 z-20 bg-black/55 backdrop-blur-sm md:hidden"
            onClick={() => setMobileNavOpen(false)}
          />
        ) : null}
        <aside
          id="app-sidebar"
          className={`${mobileNavOpen ? "fixed" : "hidden"} inset-y-0 left-0 z-30 w-[280px] overflow-y-auto pt-16 shadow-2xl md:sticky md:top-0 md:block md:h-screen md:w-[260px] md:shrink-0 md:pt-0 md:shadow-none`}
        >
          <Sidebar role={role} pathname={pathname} />
        </aside>
        <div className="workspace min-w-0 flex-1 pt-16 md:pt-0">
          <header className="hidden h-14 items-center justify-between border-b border-border/80 bg-white/60 px-8 backdrop-blur md:flex">
            <div className="flex items-center gap-3">
              <span className="eyebrow">TrinolIT</span>
              <span className="h-3 w-px bg-border" />
              <span className="text-xs text-muted-foreground">
                Company operating system
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              <span className="font-medium text-foreground">
                {role ? role.toLowerCase() : "session"}
              </span>
            </div>
          </header>
          <main className="workspace-content px-4 py-6 sm:px-6 md:px-8 md:py-8 lg:px-10">
            {children}
          </main>
        </div>
      </div>
    </RoleProvider>
  );
}
