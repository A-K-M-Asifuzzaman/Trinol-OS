# Trinol OS — Authentication & Sessions

Decision records: [ADR-0013](../adr/0013-firebase-as-identity-provider.md)
(identity provider), [ADR-0002](../adr/0002-opaque-server-sessions.md)
(session mechanism).

## 1. Model

**Firebase Authentication proves who you are. Trinol OS decides what you may do
and when access ends.**

- Firebase owns credentials, password reset, email verification, MFA and Google
  sign-in. We store no passwords.
- The browser signs in with Firebase, posts the resulting ID token **once** to
  `POST /api/v1/auth/session`, and discards it.
- The API verifies that token, resolves the local user, and issues an opaque
  server-side session: a row in `sessions` plus an `HttpOnly` cookie holding a
  random token whose SHA-256 lives in that row.
- Every request thereafter is authenticated by that cookie. No Firebase call, no
  JWT in the browser.

Why not carry Firebase ID tokens as the request credential: they sit in browser
storage where XSS can read them, they cannot be revoked promptly without a
network round-trip to Google on every request, and a role change would not take
effect until the client refreshed its token. Revocation with a session row is
`UPDATE sessions SET revoked_at = now()`. Full reasoning in ADR-0013.

## 2. Token and cookie

```
token      = secrets.token_urlsafe(32)          # 256 bits, never stored
token_hash = sha256(token)                       # stored, unique index
```

Cookie `trinol_session`:

| Attribute | Value |
|---|---|
| `HttpOnly` | yes — JavaScript must never read it |
| `Secure` | yes (dev over http://localhost is the only exception) |
| `SameSite` | `Lax` |
| `Path` | `/` |
| `Max-Age` | absent — a session cookie; lifetime is enforced server-side |

SHA-256 is correct here and bcrypt/argon2 would be wrong: the token is 256 bits
of entropy, not a guessable password, so there is nothing to slow down, and a
cheap hash keeps the per-request lookup a single indexed read.

## 3. Lifetimes

- Idle timeout: **7 days** since `last_seen_at`.
- Absolute timeout: **30 days** since `created_at`, no extension.
- `last_seen_at` is refreshed at most once per 5 minutes to avoid a write on
  every request.
- Logout revokes the current session. "Log out everywhere" revokes all of the
  user's sessions. Password change and role change revoke all **other** sessions.

## 4. Credentials

Owned by Firebase. Trinol OS stores no `password_hash` and implements no
password policy, hashing, reset or verification flow.

Firebase project configuration (set once per environment, recorded in
`infrastructure/`):

- Sign-in methods: as agreed with the owner — email/password and/or Google.
- Password policy: minimum 12 characters, Firebase's compromised-password check
  enabled.
- Email enumeration protection: **on** (Firebase returns a generic error rather
  than revealing whether an address is registered).
- Separate Firebase projects for dev, staging and production.

## 5. Token exchange and login protection

`POST /api/v1/auth/session` is the only endpoint that accepts a Firebase ID
token. It:

1. Verifies the token offline against Google's cached public keys — checking
   signature, expiry, `aud` (our project id) and `iss`. A token minted for any
   other Firebase project is rejected.
2. Requires `email_verified == true`.
3. Resolves `users.firebase_uid`. Unknown uid with no open invitation and no
   existing membership → `403`. **No account is auto-created**; without this,
   enabling Google sign-in would admit any Google account on the internet.
4. Rejects a membership that is missing or `INACTIVE`.
5. Creates the session row and sets the cookie.

Firebase applies its own abuse throttling to sign-in attempts. We additionally
rate-limit the exchange endpoint per IP, because it is unauthenticated and
performs database work.

A successful exchange writes an `is_audit` activity event with IP and user agent.
So does a rejection at step 3 or 4 — a valid Firebase identity with no local
access is worth seeing.

The verifier sits behind an `IdentityVerifier` protocol so tests never touch the
network.

## 6. CSRF

`SameSite=Lax` blocks cross-site POSTs from forms, but it is not the whole
answer (it does nothing about a same-site subdomain takeover, and browser
behaviour varies). Defence in depth on every unsafe method
(`POST/PUT/PATCH/DELETE`):

1. `Origin` (falling back to `Referer`) must match the configured app origin.
   A missing Origin on an unsafe method is rejected.
2. Double-submit token: `csrf_hash` on the session row, the raw value returned
   from `GET /api/v1/auth/session` and echoed by the client in `X-CSRF-Token`.

Both checks are middleware. They are not per-route decorators — a new route must
not be able to forget them.

## 7. Session → organization

A session is bound to exactly one `organization_id`. V1 has one organization, so
this is invisible, but binding it now means the multi-org switcher later is a
"create a new session for org B" endpoint rather than a rewrite of every
authorization check.

Every request resolves `(user, organization, membership.role)` in one indexed
join. A session whose membership has been removed, or whose membership status is
`INACTIVE`, is rejected at authentication time — not at authorization time.

## 8. Password reset and email verification

Handled entirely by Firebase, including the emails. The app links to Firebase's
flows; it does not implement them.

One local obligation: a password change or reset does not touch our session
rows, so a user who resets a stolen password would otherwise leave the attacker's
session alive. Firebase records `tokens_valid_after_time` on such an event; the
exchange endpoint and a lightweight periodic reconciliation revoke local sessions
created before that timestamp.
`ponytail: reconciliation on next exchange plus a daily sweep; move to a
Firebase Auth blocking function or webhook if near-instant revocation is needed.`

## 9. Endpoints (Phase 1)

```
POST   /api/v1/auth/session          → exchange Firebase ID token for a session
GET    /api/v1/auth/session          → current user, org, role, csrf token
DELETE /api/v1/auth/session          → logout (revoke this session)
DELETE /api/v1/auth/sessions         → log out everywhere
POST   /api/v1/invitations/accept
```

There is no public self-signup and no local password endpoint. Users exist
because an OWNER/ADMIN invited them — this is internal company software first
([ADR-0012](../adr/0012-v1-scope-trims.md)).

## 10. Next.js side

The Firebase JS SDK is loaded on the login page only. It holds an ID token for
the few seconds between sign-in and exchange, then `signOut()` clears it. No
other route ships the SDK.

After login the browser never holds a token in JavaScript. Server components
read the incoming session cookie and forward it on the server-side fetch to
FastAPI; client components rely on the browser attaching it automatically.

The Firebase web config (`apiKey`, `authDomain`, project id) is public by design
and may live in `NEXT_PUBLIC_*`. The **service-account credentials are not** —
they are server-side only, injected as `FIREBASE_CREDENTIALS`.

Middleware may redirect an obviously-unauthenticated request to `/login` as a
UX shortcut, but **that is not authorization** — every API response is
independently authenticated and authorized server-side.
