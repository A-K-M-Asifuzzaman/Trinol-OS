import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

// NEXT_PUBLIC_E2E_TEST_MODE is read as a module-level constant at import
// time, so it must be stubbed *before* the page module is imported — a
// separate file (not a case inside login.test.tsx) keeps that stub from
// ever leaking into the "must never render by default" assertions there.
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));
vi.mock("@/lib/firebase/client", () => ({
  signInWithEmailPassword: vi.fn(async () => "fake-id-token"),
  signInWithGoogle: vi.fn(async () => "fake-id-token"),
}));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    exchangeSession: vi.fn(async (idToken: string) => ({
      user_id: idToken,
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

describe("LoginPage with NEXT_PUBLIC_E2E_TEST_MODE enabled", () => {
  beforeAll(() => {
    vi.stubEnv("NEXT_PUBLIC_E2E_TEST_MODE", "true");
  });
  afterAll(() => {
    vi.unstubAllEnvs();
  });

  it("renders the E2E test-login form and signs in with a plain email", async () => {
    const { default: LoginPage } = await import("@/app/(auth)/login/page");
    const { exchangeSession } = await import("@/lib/api/client");
    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/e2e test email/i), {
      target: { value: "founder@trinolit.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /e2e test sign in/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/dashboard"));
    expect(exchangeSession).toHaveBeenCalledWith("founder@trinolit.com");
  });
});
