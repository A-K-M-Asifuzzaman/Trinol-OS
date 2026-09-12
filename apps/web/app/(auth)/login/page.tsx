"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  exchangeSession,
  fetchSessionInfo,
  setCsrfToken,
} from "@/lib/api/client";
import {
  signInWithEmailPassword,
  signInWithGoogle,
} from "@/lib/firebase/client";

const schema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});
type FormValues = z.infer<typeof schema>;

const e2eSchema = z.object({
  email: z.string().email("Enter a valid email address"),
});
type E2EFormValues = z.infer<typeof e2eSchema>;

// Stage 11 (Playwright E2E): only rendered when NEXT_PUBLIC_E2E_TEST_MODE is
// set, which is never true in a real deployment (unset by default — see
// .env.example). Lets Playwright log in as a seeded user without a real
// Firebase project; the backend's own E2EIdentityVerifier gate (deps.py) is
// the actual security boundary, not this UI conditional.
const E2E_TEST_MODE = process.env.NEXT_PUBLIC_E2E_TEST_MODE === "true";

export default function LoginPage() {
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });
  const {
    register: registerE2E,
    handleSubmit: handleSubmitE2E,
    formState: { errors: e2eErrors },
  } = useForm<E2EFormValues>({ resolver: zodResolver(e2eSchema) });

  // AUTH.md §5: verify with Firebase, exchange the ID token for our own
  // session, then read the CSRF token GET /auth/session returns so
  // subsequent unsafe requests can attach it (AUTH.md §6, double-submit).
  async function completeSignIn(idToken: string) {
    await exchangeSession(idToken);
    const info = await fetchSessionInfo();
    setCsrfToken(info.csrf_token);
    router.push("/dashboard");
  }

  function describeError(err: unknown): string {
    return err instanceof ApiError
      ? err.message
      : "Sign-in failed. Please try again.";
  }

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    setSubmitting(true);
    try {
      const idToken = await signInWithEmailPassword(
        values.email,
        values.password,
      );
      await completeSignIn(idToken);
    } catch (err) {
      setFormError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  });

  async function onGoogleSignIn() {
    setFormError(null);
    setSubmitting(true);
    try {
      const idToken = await signInWithGoogle();
      await completeSignIn(idToken);
    } catch (err) {
      setFormError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  // E2EIdentityVerifier (deps.py) treats the "id_token" as the plain email
  // of a pre-existing (seeded) user — no real Firebase round-trip.
  const onE2ESubmit = handleSubmitE2E(async (values) => {
    setFormError(null);
    setSubmitting(true);
    try {
      await completeSignIn(values.email);
    } catch (err) {
      setFormError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <main className="grid min-h-screen bg-[#111214] lg:grid-cols-[minmax(0,1.1fr)_minmax(28rem,0.9fr)]">
      <section className="relative hidden overflow-hidden border-r border-white/10 p-12 text-white lg:flex lg:flex-col lg:justify-between xl:p-16">
        <div
          aria-hidden="true"
          className="absolute inset-0 opacity-30 [background-image:linear-gradient(rgba(255,255,255,.08)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.08)_1px,transparent_1px)] [background-size:64px_64px]"
        />
        <div className="relative flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-sm border border-white/20 bg-white/[0.04] text-sm font-black">
            T/
          </span>
          <div>
            <p className="font-bold">Trinol OS</p>
            <p className="text-xs text-zinc-500">Built by TrinolIT</p>
          </div>
        </div>
        <div className="relative max-w-2xl">
          <span className="mb-7 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.03] px-3 py-1 text-[11px] font-bold tracking-[0.12em] text-zinc-400 uppercase">
            <span className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--signal))]" />
            Internal operations
          </span>
          <h1 className="max-w-xl text-5xl font-bold leading-[0.98] tracking-[-0.055em] xl:text-6xl">
            One clear view of the company.
          </h1>
          <p className="mt-6 max-w-lg text-base leading-7 text-zinc-400">
            Projects, clients, meetings, finance, and company
            knowledge—connected in one operating system.
          </p>
        </div>
        <div className="relative flex items-center justify-between border-t border-white/10 pt-5 text-xs text-zinc-600">
          <span>Software · AI · Systems</span>
          <span>Private workspace</span>
        </div>
      </section>

      <section className="flex min-h-screen items-center justify-center bg-background px-5 py-10 sm:px-10">
        <div className="w-full max-w-md">
          <div className="mb-10 lg:hidden">
            <p className="text-sm font-bold">Trinol OS</p>
            <div className="mt-2 h-1 w-10 bg-[hsl(var(--signal))]" />
          </div>
          <p className="eyebrow mb-3">Secure workspace</p>
          <h2 className="text-3xl font-bold tracking-[-0.04em]">
            Welcome back
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Sign in to continue to Trinol OS.
          </p>
          <form onSubmit={onSubmit} className="mt-8 space-y-4" noValidate>
            <div>
              <label htmlFor="email" className="text-sm font-medium">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                className="mt-1.5 h-11 w-full rounded border border-border px-3 text-sm"
                {...register("email")}
              />
              {errors.email ? (
                <p className="mt-1 text-sm text-destructive">
                  {errors.email.message}
                </p>
              ) : null}
            </div>
            <div>
              <label htmlFor="password" className="text-sm font-medium">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                className="mt-1.5 h-11 w-full rounded border border-border px-3 text-sm"
                {...register("password")}
              />
              {errors.password ? (
                <p className="mt-1 text-sm text-destructive">
                  {errors.password.message}
                </p>
              ) : null}
            </div>
            {formError ? (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            ) : null}
            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "Signing in..." : "Sign in"}
            </Button>
          </form>
          <div className="my-5 flex items-center gap-3 text-[11px] font-medium tracking-wider text-muted-foreground uppercase">
            <span className="h-px flex-1 bg-border" /> or{" "}
            <span className="h-px flex-1 bg-border" />
          </div>
          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={onGoogleSignIn}
            disabled={submitting}
          >
            Continue with Google
          </Button>
          {E2E_TEST_MODE ? (
            <form
              onSubmit={onE2ESubmit}
              className="mt-6 space-y-3 border-t border-border pt-6"
              noValidate
            >
              <div>
                <label htmlFor="e2e-email" className="text-sm font-medium">
                  E2E test email
                </label>
                <input
                  id="e2e-email"
                  type="email"
                  className="mt-1.5 h-11 w-full rounded border border-border px-3 text-sm"
                  {...registerE2E("email")}
                />
                {e2eErrors.email ? (
                  <p className="mt-1 text-sm text-destructive">
                    {e2eErrors.email.message}
                  </p>
                ) : null}
              </div>
              <Button
                type="submit"
                variant="outline"
                disabled={submitting}
                className="w-full"
              >
                E2E test sign in
              </Button>
            </form>
          ) : null}
          <p className="mt-8 text-center text-xs text-muted-foreground">
            Authorized TrinolIT team members only.
          </p>
        </div>
      </section>
    </main>
  );
}
