# Trinol OS — Security

Companion documents: [AUTH.md](AUTH.md), [RBAC.md](RBAC.md),
[DATABASE.md §5](DATABASE.md#5-organization-isolation).

## 1. Trust boundaries

| Boundary | Rule |
|---|---|
| Browser → Next.js | Untrusted input. Next.js makes no authorization decision. |
| Next.js → FastAPI | Cookie is forwarded, never minted. Next.js has no service credential. |
| FastAPI → Postgres | Least-privilege role; app role has no `UPDATE/DELETE` on `activity_events`, no DDL. |
| Public internet → `/api/public/*` | Hostile by default: rate limited, size limited, validated, logged. |
| Browser → `POST /auth/session` | A Firebase ID token proves identity, never authorization. Signature, `aud`, `iss`, expiry and `email_verified` all checked; local membership decides access. |

Secrets live in the environment, injected by the deployment, never in the repo,
never in `NEXT_PUBLIC_*`. `.env.example` carries names and dummy values only.
A pre-commit secret scan (`gitleaks`) runs in CI.

## 2. Top risks for this system

Ranked by likelihood × blast radius, with the mitigation each one gets:

1. **Cross-organization data leak** — a query missing its org filter.
   → single scoped-session choke point + runtime guard + isolation test matrix.
2. **Missing authorization on a new endpoint** — the classic.
   → startup check that fails boot on any route lacking `require(...)` or `@public`.
3. **Privilege escalation via role edit** — admin promotes self to owner.
   → [RBAC.md §5](RBAC.md#5-escalation-guards).
4. **Public contact endpoint abused** — spam floods the CRM and the mailbox.
   → §5 below.
5. **Financial tampering** — totals computed client-side or edited on a sent invoice.
   → totals recomputed server-side, DB check constraints, immutability rules
   ([ADR-0007](../adr/0007-money-and-invoice-totals.md)).
6. **Malicious upload served back** — stored XSS via an attachment.
   → §6 below.
7. **Credential stuffing** — reused passwords against a small company.
   → Firebase owns credentials: its throttling, compromised-password check and
   optional MFA, plus our own rate limit on the token-exchange endpoint.
8. **Over-permissive Firebase sign-in** — Google sign-in enabled means any
   Google account can obtain a valid ID token.
   → the exchange endpoint never auto-creates users; an identity with no
   invitation and no membership gets `403`
   ([ADR-0013](../adr/0013-firebase-as-identity-provider.md)).

## 3. Transport and headers

HTTPS only; HSTS with `max-age=31536000; includeSubDomains` once the domain is
confirmed HTTPS-only. Set on every response:

```
Content-Security-Policy: default-src 'self'; img-src 'self' data: https:;
  object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
Referrer-Policy: strict-origin-when-cross-origin
X-Content-Type-Options: nosniff
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

CSP is written with a nonce from the start. Next.js can be coaxed into
`unsafe-inline` for convenience; that is not taken, because retrofitting a
strict CSP later is far more work than starting with one.

CORS: the app origin is same-origin, so credentialed cross-origin requests are
**disabled**. There is no `Access-Control-Allow-Origin: *` anywhere. The public
contact endpoint is the single exception and allows exactly
`https://www.trinolit.com` for `POST` only.

## 4. Input validation

Pydantic v2 models on every request body, query and path parameter, with
explicit `max_length` on every string — an unbounded text field is a memory and
storage abuse vector. Global request body cap of 1 MiB (multipart excepted).

Output is escaped by React. Any rich text is stored as Markdown and rendered
through a sanitizing pipeline with an allowlist; raw HTML from users is never
inserted, and `dangerouslySetInnerHTML` is banned by an ESLint rule.

SQL is always parameterized through SQLAlchemy. Raw `text()` with interpolation
is banned by a lint rule.

## 5. Public contact endpoint

`POST /api/public/contact` is the only unauthenticated write in the system.

- Rate limit: 5/hour per IP, 20/hour per email, 100/hour global. Postgres-backed
  fixed window; over the limit returns `429` with `Retry-After`.
- Body cap 8 KiB; `message` max 5000 chars.
- Honeypot field plus a minimum form-fill time — both free, both stop the
  volume of low-effort bots. If real spam persists, add Turnstile; not before.
- Every submission stored raw in `contact_submissions` with IP and user agent,
  **then** a Lead is created. Storing first means a failure in lead creation or
  email never loses the customer's enquiry.
- Notification and confirmation emails are queued after the transaction commits,
  and a mail failure never fails the HTTP response.
- Response is a generic `202` with a reference number — it does not reveal
  whether a lead was created or deduplicated.

## 6. File uploads

- `FileStorage` protocol with two implementations: local filesystem (dev) and
  S3-compatible (prod). Chosen by config, one interface, no third variant
  "for later".
- Validated on upload: size cap (10 MiB default, per-type overrides), extension
  allowlist, and **sniffed** content type — the client's `Content-Type` is a
  hint, not evidence. Mismatch is a rejection.
- The original filename is never used as a storage key. Keys are
  `{org_id}/{uuid7}{ext}`; the display name is stored in the database column.
- Downloads go through an authorized API route that checks org and resource
  access, then streams with `Content-Disposition: attachment` and
  `X-Content-Type-Options: nosniff`. No public bucket, no guessable direct URL.
- SVG uploads are rejected for avatars and attachments (scriptable). PNG/JPG/WebP
  and documents only.

## 7. Email safety

See [EMAIL.md](EMAIL.md). Headline rules: SMTP credentials are server-side only,
never in `NEXT_PUBLIC_*`; all user-supplied content in templates is escaped;
header values are sanitized against injection of newlines.

## 8. Logging and data handling

Never logged: passwords, session tokens, CSRF tokens, reset tokens, cookies,
`Authorization` headers, full auth request bodies. Email addresses appear in
logs only where operationally necessary. A redaction filter on the logging
handler enforces this rather than relying on discipline at each call site.

Backups are encrypted at rest and their restore path is tested before Phase 5
puts real financial data in them.

## 9. Dependency hygiene

Pinned lockfiles, Dependabot on, `pip-audit` and `npm audit` in CI. Adding a
dependency requires a one-line justification in the PR — the answer to "can a
few lines of stdlib do this?" is usually yes.

## 10. Verification

The security test suite is a first-class part of CI and must include:
unauthenticated access to every protected route; cross-org access to every
org-scoped route; privilege escalation attempts per [RBAC.md §5](RBAC.md#5-escalation-guards);
rate-limit enforcement on login and contact; upload of a mismatched content
type; and CSRF-missing/origin-mismatch rejections.
