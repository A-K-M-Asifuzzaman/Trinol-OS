import { cookies } from "next/headers";

/** AUTH.md §10: server components read the incoming session cookie and
 * forward it on the server-side fetch to FastAPI (Node's fetch, unlike the
 * browser's, doesn't attach cookies automatically — there's no browser
 * session to attach them from). Shared by every server component that
 * needs it, rather than each re-deriving the same serialization. */
export async function getServerCookieHeader(): Promise<string> {
  const cookieStore = await cookies();
  return cookieStore
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
}
