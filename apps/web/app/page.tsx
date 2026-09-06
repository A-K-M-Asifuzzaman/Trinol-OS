import { redirect } from "next/navigation";

export default function RootPage() {
  // Middleware may later redirect an obviously-unauthenticated request as a
  // UX shortcut (AUTH.md §10) — that's not built yet, and every API response
  // is independently authorized regardless, so this is only ever a landing
  // convenience, not a security boundary.
  redirect("/login");
}
