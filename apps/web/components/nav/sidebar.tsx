import Link from "next/link";

// MASTER_PROMPT §7's nav groups. Only Team has a real destination in Phase 1
// (Stage 9's memberships endpoints) — everything else renders as a disabled
// label until its own phase builds the page behind it.
//
// RBAC.md §2: "Finance is invisible to MEMBER and MANAGER — not merely
// hidden in navigation. The endpoints return 403 ..." Nav-hiding it is the
// UX half of that rule (the 403 is the API's job, already true since
// FINANCE_READ is ADMIN-tier in core/authz/permissions.py) — marked so
// Sidebar can filter the whole group out for those two roles.
const NAV_GROUPS: ReadonlyArray<{
  label: string;
  items: ReadonlyArray<{ label: string; href?: string }>;
  restrictedToAdminPlus?: boolean;
}> = [
  {
    label: "WORK",
    items: [
      { label: "My Work" },
      { label: "Projects" },
      { label: "Tasks" },
      { label: "Calendar" },
    ],
  },
  {
    label: "SALES",
    items: [{ label: "Leads" }, { label: "Clients" }, { label: "Pipeline" }],
  },
  {
    label: "COMPANY",
    items: [
      { label: "Team", href: "/team" },
      { label: "Meetings" },
      { label: "Documents" },
    ],
  },
  {
    label: "FINANCE",
    restrictedToAdminPlus: true,
    items: [
      { label: "Overview" },
      { label: "Income" },
      { label: "Expenses" },
      { label: "Invoices" },
    ],
  },
  { label: "INSIGHTS", items: [{ label: "Reports" }, { label: "Activity" }] },
  { label: "SETTINGS", items: [] },
];

const ADMIN_PLUS_ROLES = new Set(["ADMIN", "OWNER"]);

export function Sidebar({ role }: { role: string | null }) {
  const groups = NAV_GROUPS.filter(
    (group) =>
      !group.restrictedToAdminPlus ||
      (role !== null && ADMIN_PLUS_ROLES.has(role)),
  );

  return (
    <nav className="w-full border-b border-border p-4 md:w-56 md:shrink-0 md:border-b-0 md:border-r">
      <div className="mb-4 text-sm font-semibold">Trinol OS</div>
      <Link
        href="/dashboard"
        className="block rounded px-2 py-1 text-sm hover:bg-muted"
      >
        Dashboard
      </Link>
      {groups.map((group) => (
        <div key={group.label} className="mt-4">
          <p className="px-2 text-xs font-semibold uppercase text-muted-foreground">
            {group.label}
          </p>
          <ul className="mt-1 space-y-1">
            {group.items.map((item) => (
              <li key={item.label}>
                {item.href ? (
                  <Link
                    href={item.href}
                    className="block rounded px-2 py-1 text-sm hover:bg-muted"
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span
                    aria-disabled="true"
                    className="block cursor-not-allowed rounded px-2 py-1 text-sm text-muted-foreground/60"
                  >
                    {item.label}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
