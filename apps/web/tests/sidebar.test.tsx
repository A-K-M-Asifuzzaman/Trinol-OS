import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Sidebar } from "@/components/nav/sidebar";

// RBAC.md §2: "Finance is invisible to MEMBER and MANAGER — not merely
// hidden in navigation." Codex Stage 10 review: the sidebar rendered Finance
// unconditionally, for every role.
describe("Sidebar", () => {
  it.each(["MEMBER", "MANAGER"])("hides Finance for %s", (role) => {
    render(<Sidebar role={role} />);
    expect(screen.queryByText("FINANCE")).not.toBeInTheDocument();
  });

  it.each(["ADMIN", "OWNER"])("shows Finance for %s", (role) => {
    render(<Sidebar role={role} />);
    expect(screen.getByText("FINANCE")).toBeInTheDocument();
  });

  it("hides Finance when the role couldn't be resolved", () => {
    render(<Sidebar role={null} />);
    expect(screen.queryByText("FINANCE")).not.toBeInTheDocument();
  });

  it("always shows Team, regardless of role", () => {
    render(<Sidebar role="MEMBER" />);
    expect(screen.getByRole("link", { name: "Team" })).toBeInTheDocument();
  });
});
