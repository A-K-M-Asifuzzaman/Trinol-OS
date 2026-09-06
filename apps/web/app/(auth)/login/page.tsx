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

export default function LoginPage() {
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

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

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        <h1 className="text-xl font-semibold">Sign in to Trinol OS</h1>
        <form onSubmit={onSubmit} className="space-y-3" noValidate>
          <div>
            <label htmlFor="email" className="text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
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
              className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
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
        <Button
          type="button"
          variant="outline"
          className="w-full"
          onClick={onGoogleSignIn}
          disabled={submitting}
        >
          Continue with Google
        </Button>
      </div>
    </main>
  );
}
