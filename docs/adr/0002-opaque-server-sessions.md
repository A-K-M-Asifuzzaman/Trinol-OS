# ADR-0002 — Opaque server-side sessions instead of JWT

Status: Accepted (Phase 0), amended by
[ADR-0013](0013-firebase-as-identity-provider.md) — the session mechanism below
stands unchanged; credentials moved to Firebase, so the local password handling
described here no longer applies.

## Context

MASTER_PROMPT §27 asks for secure auth, session management, and "refresh-token
rotation *if* a JWT architecture is selected" — leaving the choice open. The web
and API tiers share one database and one origin.

## Decision

Session = a row in `sessions`. The cookie carries 256 bits of random token; the
database stores its SHA-256. `HttpOnly; Secure; SameSite=Lax`. Details in
[AUTH.md](../architecture/AUTH.md).

## Alternatives rejected

**JWT access + refresh rotation.** JWT's advantage is verifying a token without
touching the database. That advantage does not exist here: the API queries the
same PostgreSQL on every request anyway. Adopting it would buy a refresh
endpoint, rotation and reuse-detection logic, a revocation blocklist (a database
lookup — precisely what JWT was meant to avoid), signing-key management and
rotation, and clock-skew handling. That is a large amount of security-critical
code purchased with no benefit.

**JWT in localStorage.** Rejected outright: readable by any XSS.

**Third-party identity provider.** Real value at SaaS scale (SSO, SCIM), no
value for an internal tool with a handful of accounts. Revisit at V4.

## Consequences

- Revocation is immediate and trivially correct — logout, "log out everywhere",
  password change and role change all just write `revoked_at`.
- One indexed lookup per request, on a table with a few dozen rows for years.
- The API is not stateless. It was never going to be; it has a database.
- SSO later means adding an authentication *source*, not replacing the session
  model — the session row stays.
