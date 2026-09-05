# Trinol OS — Architecture

Status: Phase 0 design. No implementation exists yet.

## 1. Shape of the system

Two deployable units plus a database:

```
browser
  │
  ▼
Next.js (apps/web)          ── server components render read views,
  │                            forwarding the session cookie to the API
  │  /api/* rewrite
  ▼
FastAPI (apps/api)          ── all business rules, authorization, persistence
  │
  ├── PostgreSQL            ── system of record
  ├── object storage (S3-compatible) ── attachments
  ├── SMTP                  ── transactional email
  └── Firebase Auth         ── identity provider, at login only
```

Firebase proves identity once, at login; the API exchanges its ID token for a
local session cookie and never calls Firebase again on the request path
([ADR-0013](../adr/0013-firebase-as-identity-provider.md)).

Next.js is a rendering and interaction layer. It holds **no** business rules and
performs **no** authorization decisions. It never talks to PostgreSQL.

Web and API are served from one origin (`app.trinolit.com`, with `/api/*`
proxied to FastAPI). That is what makes a `SameSite=Lax` session cookie work
without CORS credentials or a token in JavaScript. See [AUTH.md](AUTH.md).

Redis is **not** in V1. Rate limiting uses a Postgres table; there is no cache
layer and no background worker yet. Added when a real need appears
(see [ADR-0010](../adr/0010-no-redis-or-worker-in-v1.md)).

## 2. Repository layout

```
trinol-os/
├── apps/
│   ├── api/                 FastAPI, Python 3.12
│   │   ├── src/trinol/
│   │   │   ├── core/        config, db, security, errors, logging, deps
│   │   │   ├── modules/     one package per domain module (§3)
│   │   │   ├── platform/    activity, notifications, files, email, search
│   │   │   └── main.py
│   │   ├── migrations/      Alembic
│   │   └── tests/
│   └── web/                 Next.js App Router, TypeScript
│       ├── app/
│       │   ├── (auth)/      login, password reset — unauthenticated shell
│       │   └── (app)/       dashboard and all authenticated routes
│       ├── components/      ui/ (shadcn) + feature components
│       ├── lib/             api client, generated types, hooks
│       └── tests/
├── infrastructure/          compose files, Caddyfile, deploy scripts
├── docs/                    architecture/, adr/, product/
├── scripts/
├── docker-compose.yml
└── .env.example
```

There is **no `packages/shared`**. The only thing V1 would share is types, and
those are generated from the API's OpenAPI schema into
`apps/web/lib/api/types.gen.ts` — one build step instead of a package that must
be versioned, built and kept in sync ([ADR-0005](../adr/0005-api-conventions-and-generated-types.md)).

## 3. Domain modules

Each module owns its tables, its service layer and its routes. Modules talk to
each other through service functions, never by reaching into another module's
tables.

| Module | Owns | Phase |
|---|---|---|
| `identity` | User, Organization, Membership, Session, Invitation | 1 |
| `work` | Project, ProjectMember, Milestone, Task, TaskComment, TaskChecklistItem, TaskAttachment | 2 |
| `crm` | Client, Lead, LeadStageEvent, ContactSubmission | 3 |
| `meetings` | Meeting, MeetingParticipant, MeetingDecision, MeetingAction | 4 |
| `finance` | Income, Expense, Invoice, InvoiceItem, Payment, InvoiceCounter | 5 |
| `platform` | ActivityEvent, Notification, DocumentReference, FileObject | cross-cutting |

Dependency direction is one-way: `platform` ← everything, `identity` ← everything,
and otherwise `work → crm` (project belongs to a client), `meetings → work/crm`,
`finance → work/crm`. No cycles. `crm` must not import from `work`; the
lead→project conversion lives in `work` because that is where the Project is
created.

The two documented cross-module writes:

- **Lead → Client + Project** (Phase 3): one transaction in `work.services.convert_lead`.
- **MeetingAction → Task** (Phase 4): one transaction in `meetings.services.promote_action`.

## 4. Request path

```
HTTP → request_id middleware → session auth dependency
     → org resolution (membership lookup)
     → permission dependency (RBAC.md)
     → route handler (Pydantic in/out, no logic)
     → service function (business rules, transaction boundary)
     → repository / SQLAlchemy (always org-scoped)
     → PostgreSQL
```

Rules:

- Routes are thin. Validation via Pydantic v2, orchestration via services.
- The **service function is the transaction boundary.** Routes do not commit.
- Every query against an org-scoped table goes through the scoped session
  helper. See [DATABASE.md §5](DATABASE.md#5-organization-isolation).
- Activity events are emitted inside the same transaction as the change they
  describe, so the feed can never disagree with the data.

## 5. Frontend architecture

- **App Router**, server components by default. Lists and detail pages are
  server-rendered: the server component calls the API with the incoming cookie
  and passes plain data down.
- **Client components** only where there is real interaction: Kanban
  drag-and-drop, filter bars, forms, command palette. Those use TanStack Query
  against the same API.
- **Forms**: React Hook Form + Zod. The Zod schema mirrors the API's contract
  for fast feedback; the API re-validates everything. Client validation is UX,
  never a control.
- **State**: server state lives in TanStack Query. No Redux/Zustand until
  something genuinely cross-page and non-server appears.
- **Errors**: the API client maps the error envelope (§6) to typed errors;
  `error.tsx` per route group renders a real message, never a raw 500.
- **Every list route** ships four states: loading skeleton, empty, error,
  populated. This is a review gate, not a suggestion.

## 6. API conventions

Full detail in [ADR-0005](../adr/0005-api-conventions-and-generated-types.md).
Summary:

- REST under `/api/v1/`, plural nouns, UUIDv7 ids in paths.
- Collections: `?limit=&offset=&sort=&q=` plus resource filters. `limit`
  defaults to 50, hard cap 200. Response: `{"items": [...], "total": n}`.
- Errors, always this envelope, never a bare string:

  ```json
  {"error": {"code": "TASK_NOT_FOUND", "message": "Task not found", "request_id": "01J...", "details": {}}}
  ```

- `422` for validation, `401` unauthenticated, `403` unauthorized,
  `404` for both "missing" and "not yours" (never leak cross-org existence),
  `409` for conflicts, `429` for rate limits.
- Mutating endpoints require an `Origin`/`Referer` check plus the CSRF token.

## 7. Observability

Structured JSON logs with `request_id`, `user_id`, `organization_id`, method,
route, status, latency_ms. Never log passwords, tokens, cookies or full
request bodies of auth endpoints. `/health` (process alive) and `/ready`
(DB reachable, migrations at head).

## 8. What Phase 0 deliberately did not decide

Open questions carried to the Phase 0 report, not silently resolved: hosting
target specifics, whether Google Calendar is in scope at all, and the invoice
tax model. See the Phase 0 summary in [ROADMAP.md](../../ROADMAP.md).
