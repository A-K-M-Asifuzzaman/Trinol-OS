import Link from "next/link";
import { cn } from "@/lib/utils";

const NAV_GROUPS: ReadonlyArray<{
  label: string;
  items: ReadonlyArray<{ label: string; href?: string }>;
  restrictedToAdminPlus?: boolean;
}> = [
  {
    label: "Work",
    items: [
      { label: "My Work", href: "/tasks/my" },
      { label: "Projects", href: "/projects" },
      { label: "Tasks", href: "/tasks" },
      { label: "Calendar" },
    ],
  },
  {
    label: "Sales",
    items: [
      { label: "Leads", href: "/leads" },
      { label: "Clients", href: "/clients" },
      { label: "Pipeline", href: "/pipeline" },
    ],
  },
  {
    label: "Company",
    items: [
      { label: "Team", href: "/team" },
      { label: "Meetings", href: "/meetings" },
      { label: "Documents", href: "/documents" },
    ],
  },
  {
    label: "Finance",
    restrictedToAdminPlus: true,
    items: [
      { label: "Overview", href: "/finance" },
      { label: "Income", href: "/finance/income" },
      { label: "Expenses", href: "/finance/expenses" },
      { label: "Invoices", href: "/invoices" },
    ],
  },
  {
    label: "Insights",
    items: [
      { label: "Reports", href: "/reports" },
      { label: "Assistant", href: "/assistant" },
      { label: "Activity" },
    ],
  },
];

const ADMIN_PLUS_ROLES = new Set(["ADMIN", "OWNER"]);

export function Sidebar({
  role,
  pathname,
}: {
  role: string | null;
  pathname?: string;
}) {
  const groups = NAV_GROUPS.filter(
    (group) =>
      !group.restrictedToAdminPlus ||
      (role !== null && ADMIN_PLUS_ROLES.has(role)),
  );

  function isActive(href: string) {
    if (!pathname) return false;
    if (href === "/dashboard" || href === "/finance") return pathname === href;
    if (href === "/tasks")
      return (
        pathname === href ||
        (pathname.startsWith("/tasks/") && pathname !== "/tasks/my")
      );
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  function navLink(label: string, href: string) {
    const active = isActive(href);
    return (
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        className={cn(
          "group relative flex h-9 items-center rounded-sm px-3 text-[13px] font-medium text-zinc-400 transition-colors hover:bg-white/[0.06] hover:text-white",
          active && "bg-white/[0.08] text-white",
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "mr-3 h-1.5 w-1.5 rounded-full border border-zinc-600 transition-colors group-hover:border-[hsl(var(--signal))]",
            active && "border-[hsl(var(--signal))] bg-[hsl(var(--signal))]",
          )}
        />
        {label}
        {active ? (
          <span
            aria-hidden="true"
            className="absolute inset-y-2 right-0 w-0.5 bg-[hsl(var(--signal))]"
          />
        ) : null}
      </Link>
    );
  }

  return (
    <nav className="flex min-h-full w-full flex-col bg-[#111214] px-4 py-5 text-white md:w-[260px]">
      <Link href="/dashboard" className="mb-7 flex items-center gap-3 px-2">
        <span
          className="relative grid h-9 w-9 place-items-center overflow-hidden rounded-sm border border-white/15 bg-white/[0.04]"
          aria-hidden="true"
        >
          <span className="absolute left-0 top-0 h-1 w-full bg-[hsl(var(--signal))]" />
          <span className="text-sm font-black tracking-[-0.08em]">T/</span>
        </span>
        <span>
          <span className="block text-sm font-bold tracking-[-0.02em]">
            Trinol OS
          </span>
          <span className="mt-0.5 block text-[10px] tracking-[0.14em] text-zinc-500 uppercase">
            Operations system
          </span>
        </span>
      </Link>

      <div className="space-y-5">
        {navLink("Dashboard", "/dashboard")}
        {groups.map((group) => (
          <div key={group.label}>
            <p className="mb-1.5 px-3 text-[10px] font-bold tracking-[0.14em] text-zinc-600 uppercase">
              {group.label}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <li key={item.label}>
                  {item.href ? (
                    navLink(item.label, item.href)
                  ) : (
                    <span
                      aria-disabled="true"
                      className="flex h-9 cursor-not-allowed items-center px-3 text-[13px] text-zinc-700"
                    >
                      <span
                        className="mr-3 h-1.5 w-1.5 rounded-full border border-zinc-800"
                        aria-hidden="true"
                      />
                      {item.label}
                      <span className="ml-auto text-[9px] tracking-wider uppercase">
                        Soon
                      </span>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="mt-auto border-t border-white/10 px-2 pt-4">
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--signal))] shadow-[0_0_8px_hsl(var(--signal)/0.7)]" />
          Systems operational
        </div>
      </div>
    </nav>
  );
}
