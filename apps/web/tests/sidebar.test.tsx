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

  it("shows Leads/Clients/Pipeline as real links (Phase 3 Stage 8)", () => {
    render(<Sidebar role="MEMBER" />);
    expect(screen.getByRole("link", { name: "Leads" })).toHaveAttribute(
      "href",
      "/leads",
    );
    expect(screen.getByRole("link", { name: "Clients" })).toHaveAttribute(
      "href",
      "/clients",
    );
    expect(screen.getByRole("link", { name: "Pipeline" })).toHaveAttribute(
      "href",
      "/pipeline",
    );
  });

  it("shows Meetings as a real link (Phase 4 Stage 7)", () => {
    render(<Sidebar role="MEMBER" />);
    expect(screen.getByRole("link", { name: "Meetings" })).toHaveAttribute(
      "href",
      "/meetings",
    );
  });

  it("still disables Calendar — no in-app calendar view this phase", () => {
    render(<Sidebar role="MEMBER" />);
    const calendar = screen.getByText("Calendar");
    expect(calendar).toHaveAttribute("aria-disabled", "true");
  });

  it("shows Overview/Income/Expenses/Invoices as real links for ADMIN+ (Phase 5 Stage 10)", () => {
    render(<Sidebar role="ADMIN" />);
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
      "href",
      "/finance",
    );
    expect(screen.getByRole("link", { name: "Income" })).toHaveAttribute(
      "href",
      "/finance/income",
    );
    expect(screen.getByRole("link", { name: "Expenses" })).toHaveAttribute(
      "href",
      "/finance/expenses",
    );
    expect(screen.getByRole("link", { name: "Invoices" })).toHaveAttribute(
      "href",
      "/invoices",
    );
  });
});
