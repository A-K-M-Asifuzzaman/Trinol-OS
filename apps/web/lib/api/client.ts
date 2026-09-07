import type { components } from "./types.gen";

// ARCHITECTURE.md §6: {"error": {code, message, request_id, details}}.
export interface ErrorEnvelope {
  code: string;
  message: string;
  request_id: string | null;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  status: number;
  code: string;
  requestId: string | null;
  details: Record<string, unknown>;

  constructor(status: number, envelope: ErrorEnvelope) {
    super(envelope.message);
    this.status = status;
    this.code = envelope.code;
    this.requestId = envelope.request_id;
    this.details = envelope.details;
  }
}

// ARCHITECTURE.md §1: "Web and API are served from one origin ... That is
// what makes a SameSite=Lax session cookie work without CORS credentials or
// a token in JavaScript." CORS is deliberately disabled server-side
// (SECURITY.md §3), so the browser must never call the API cross-origin —
// a relative path is same-origin by construction, and next.config.mjs's
// /api/* rewrite proxies it to FastAPI.
//
// Server components have no browser origin to be relative to (Node's fetch
// requires an absolute URL) and run outside next.config.mjs's rewrite
// entirely, so they need a real address: INTERNAL_API_URL, a server-only
// env var (never NEXT_PUBLIC_, so it's never bundled to the client) — the
// container hostname inside Docker (docker-compose.yml sets it to
// http://api:8000), or localhost:8000 for host-side `pnpm dev`.
const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8000";

function resolveUrl(path: string): string {
  return typeof window === "undefined" ? `${INTERNAL_API_URL}${path}` : path;
}

// In-memory only, per ARCHITECTURE.md §5/AUTH.md §6 — never persisted, reset
// on every page load. Set from GET /auth/session's csrf_token field.
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

const UNSAFE_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

interface ApiFetchOptions {
  method?: string;
  body?: unknown;
  /** Server components forward the incoming request's Cookie header
   * manually (AUTH.md §10) — the browser attaches its own automatically via
   * credentials: "include", so client components never pass this. */
  cookie?: string;
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (options.cookie) headers.Cookie = options.cookie;
  if (UNSAFE_METHODS.has(method) && csrfToken)
    headers["X-CSRF-Token"] = csrfToken;

  const response = await fetch(resolveUrl(path), {
    method,
    headers,
    credentials: "include",
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: ErrorEnvelope;
    } | null;
    if (payload?.error) {
      throw new ApiError(response.status, payload.error);
    }
    throw new ApiError(response.status, {
      code: "UNKNOWN_ERROR",
      message: response.statusText || "Request failed",
      request_id: null,
      details: {},
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type SessionInfo = components["schemas"]["SessionInfoResponse"];
export type SessionExchangeResponse =
  components["schemas"]["SessionExchangeResponse"];
export type Membership = components["schemas"]["MembershipResponse"];
export type MembershipList = components["schemas"]["MembershipListResponse"];

export async function fetchSessionInfo(cookie?: string): Promise<SessionInfo> {
  return apiFetch<SessionInfo>("/api/v1/auth/session", { cookie });
}

export async function exchangeSession(
  idToken: string,
): Promise<SessionExchangeResponse> {
  return apiFetch<SessionExchangeResponse>("/api/v1/auth/session", {
    method: "POST",
    body: { id_token: idToken },
  });
}

export async function fetchTeamMembers(
  options: { limit?: number; offset?: number; cookie?: string } = {},
): Promise<MembershipList> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined)
    params.set("offset", String(options.offset));
  const query = params.toString();
  return apiFetch<MembershipList>(
    `/api/v1/memberships${query ? `?${query}` : ""}`,
    {
      cookie: options.cookie,
    },
  );
}
