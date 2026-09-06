import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "@/app/(auth)/login/page";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

// AUTH.md §10: the Firebase SDK loads on this page only, and this test must
// not call it for real — mocked entirely, same as it must never reach a
// real API (the auth-exchange endpoints are covered on the backend already,
// in tests/integration/test_auth_exchange.py; this test is about the form).
vi.mock("@/lib/firebase/client", () => ({
  signInWithEmailPassword: vi.fn(async () => "fake-id-token"),
  signInWithGoogle: vi.fn(async () => "fake-id-token"),
}));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    exchangeSession: vi.fn(async () => ({
      user_id: "u1",
      organization_id: "o1",
      role: "MEMBER",
    })),
    fetchSessionInfo: vi.fn(async () => ({
      user_id: "u1",
      organization_id: "o1",
      role: "MEMBER",
      csrf_token: "tok",
    })),
    setCsrfToken: vi.fn(),
  };
});

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("signs in with email/password and redirects to the dashboard", async () => {
    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "person@trinolit.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "correct-horse-battery-staple" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/dashboard"));
  });

  it("rejects an invalid email before ever calling Firebase", async () => {
    const { signInWithEmailPassword } = await import("@/lib/firebase/client");
    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "not-an-email" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() =>
      expect(screen.getByText(/valid email/i)).toBeInTheDocument(),
    );
    expect(signInWithEmailPassword).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
  });
});
