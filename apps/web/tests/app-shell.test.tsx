import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppShell } from "@/components/nav/app-shell";

// AGENTS.md's definition of done: "responsive behavior works". Codex Stage
// 10 review: the sidebar permanently reserved 14rem with no mobile
// alternative. Below md it now starts collapsed behind a toggle.
describe("AppShell", () => {
  it("starts with the mobile nav collapsed and expands it on toggle", () => {
    render(
      <AppShell role="OWNER" csrfToken={null}>
        content
      </AppShell>,
    );

    const toggle = screen.getByRole("button", { name: /menu/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("app-sidebar")).toHaveClass("hidden");

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: /close menu/i }),
    ).toBeInTheDocument();
    expect(document.getElementById("app-sidebar")).not.toHaveClass("hidden");
  });
});
