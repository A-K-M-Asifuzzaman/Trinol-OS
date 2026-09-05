# ADR-0013 — Firebase Authentication as identity provider, local sessions

Status: Accepted (Phase 0) — amends [ADR-0002](0002-opaque-server-sessions.md)

## Context

The product owner directed that Firebase Authentication be used for auth and
will supply project credentials. ADR-0002 had specified locally-owned email +
password with Argon2id. This record replaces the credential-handling half of
that decision and keeps the session half.

## Decision

**Firebase is the identity provider. Trinol OS still owns the session.**

Firebase owns: credential storage, password reset, email verification,
multi-factor authentication, and Google sign-in.

Trinol OS owns: who exists in the organization, what role they have, what a
request is allowed to do, and when access ends.

### Login flow

```
1. Browser  → Firebase JS SDK sign-in            (password or Google)
2. Browser  → POST /api/v1/auth/session { id_token }
3. FastAPI  → firebase_admin.auth.verify_id_token(id_token)
              (offline: cached Google public keys, no per-request network call)
4. FastAPI  → look up users.firebase_uid
              ├─ found        → continue
              ├─ invited      → provision the user, consume the invitation
              └─ neither      → 403, no account is created
5. FastAPI  → create a session row, set the httpOnly cookie (ADR-0002 §2)
6. Browser  → firebase.auth().signOut() locally, discarding the ID token
```

After step 6 there is no Firebase token in the browser and no Firebase call on
any subsequent request. Every request after login is authenticated exactly as
ADR-0002 describes.

### Schema effect

`users` loses `password_hash`, `failed_login_count` and `locked_until` — Firebase
owns those concerns — and gains:

- `firebase_uid text UNIQUE NOT NULL`
- `auth_provider` (`PASSWORD | GOOGLE`), for display and support

`email` remains on the local row and is refreshed from verified token claims on
each login. It is a **cache for display and matching**, never the join key: the
`firebase_uid` is, because email addresses change.

### Provisioning

There is no auto-create. An unknown `firebase_uid` whose verified email has no
open invitation and no existing membership is rejected with `403`. Without this
rule, enabling Google sign-in would let any Google account on the internet reach
an authenticated session.

Invitation acceptance matches on the **verified** email claim only
(`email_verified == true`); an unverified claim is rejected.

## Alternatives rejected

**Firebase ID tokens as the request credential** (verify the JWT on every
call). This is the default Firebase pattern and it is the wrong fit here:

- The SDK persists the token in IndexedDB/localStorage, readable by any XSS.
- Revocation is not immediate. A revoked or demoted user keeps a valid token for
  up to an hour unless every request calls `verify_id_token(check_revoked=True)`,
  which is a network round-trip to Google on the hot path of an internal tool —
  and an outage at Google then becomes an outage here.
- Roles in custom claims would mean a role change does not take effect until the
  client refreshes its token. Our `memberships` row takes effect on the next
  request.

**Firebase session cookies** (`auth.create_session_cookie`). Closer to right,
and it does give a server-set httpOnly cookie. Rejected because it is still a
signed JWT whose revocation requires the same `check_revoked` round-trip, and it
gives up nothing we want in exchange — we would still need our own session table
for org binding and CSRF.

**Keeping locally-owned passwords** (original ADR-0002). Still defensible, but
the owner has decided, and the decision has real merit: password storage, reset
flows, verification email delivery and MFA are security-critical code we no
longer write or maintain.

## Consequences

- Argon2, login lockout, password-reset tokens and verification tokens leave our
  codebase entirely. `AUTH.md` §4, §5 and §8 shrink to "Firebase does this".
- Firebase is a **login-time** dependency only. If Firebase is unreachable,
  existing sessions keep working; only new logins fail.
- One new server-side secret: the service-account JSON, injected via
  `FIREBASE_CREDENTIALS` (path or base64). It is never in the repository, never
  in an image, and never in a `NEXT_PUBLIC_*` variable. The web client's Firebase
  config keys *are* public by design and may be `NEXT_PUBLIC_*`.
- Tests must not call Firebase. `verify_id_token` sits behind an
  `IdentityVerifier` protocol with a fake implementation in tests, which is also
  how the auth matrices in [TESTING.md](../architecture/TESTING.md) stay offline
  and fast.
- Deleting a user requires deleting them in both places; the local record is the
  one that governs access, so removal from `memberships` is what actually cuts
  them off.
- A dedicated Firebase project per environment (dev, staging, production), so a
  seeded database can never authenticate a production account.
