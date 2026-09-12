# ADR-0014 — OpenAI provider, synchronous calls, finance never embedded

Status: Accepted (Phase 8, Stage 1) — recorded at the start of the phase and
extended as later stages land (Stage 3 adds pgvector specifics; this record
is amended, not replaced, if a later stage's design changes anything here).

## Context

MASTER_PROMPT §30 puts every AI feature in a "Later" bucket with two hard
rules: "Do not make V1 dependent on an LLM" and "Do not let an LLM calculate
authoritative financial totals." §39 schedules Phase 8 once real company
data exists and sequences it explicitly: "Start with meeting summary/action
extraction." Neither document names a provider, a synchronous-vs-background
execution model, or how a cross-module retrieval index should be kept from
leaking data a user can't otherwise see — those are this phase's own
decisions, recorded here so they aren't re-derived (or re-litigated)
mid-stage.

## Decision

**Provider: OpenAI**, for both chat completions and embeddings — chosen by
the product owner over Anthropic or a provider-agnostic abstraction layer.
The `openai` Python SDK is the only AI vendor dependency; there is no
provider-swapping shim, since nothing in this project asks for one.

**Every LLM/embedding call is synchronous, inside the request an explicit
user action triggers** (Summarize / Extract actions / Ask the assistant /
Score a lead) — the same pattern this codebase already uses for PDF
rendering and SMTP email, and it does not revisit
[ADR-0010](0010-no-redis-or-worker-in-v1.md) ("no Redis or worker in V1").
No queue, no cron, no background worker is introduced by this phase. If a
future stage's data volume makes a bounded per-request reindex batch too
slow, that is the trigger ADR-0010 already names ("any job that must run
reliably off the request path"), to be revisited then, not preemptively now.

**A new `ai` module** (ARCHITECTURE.md §3), not `platform`: retrieval and
scoring need to call into `meetings`/`crm`/`work` services, and cross-module
reads for a financial fact (below) into `finance` — the same reasoning that
moved `DocumentReference` out of `platform` in Phase 6. `ai → meetings/crm/
work/finance` is a new one-way edge; nothing in those four modules ever
imports `ai`.

**Financial rows are never embedded, at all.** No `KnowledgeChunk` (Stage 3)
can ever originate from `Income`/`Expense`/`Invoice`/`Payment` — there is no
`FINANCE` value in that table's source-type enum. The company assistant's
only access to financial figures is one direct, already-`FINANCE_READ`-gated
service call (`finance.services.dashboard_service`), invoked only when the
asking actor's role actually holds that permission, with its output injected
into the model's context as a labeled block the system prompt is told never
to alter. This is the concrete, mechanical form of §30's "do not let an LLM
calculate authoritative financial totals" rule: the number stated back to a
user is always the literal return value of an existing deterministic
service, never a vector-similarity guess and never model arithmetic — and,
structurally, there is no vector index containing a dollar figure that could
ever leak to a role that shouldn't see it.

**Every other retrieval-candidate's visibility is re-validated live against
its source module's own existing rule at query time** (Stage 4) — never
trusted from metadata cached on the chunk row itself. A meeting chunk is
re-checked against `meeting_service.ensure_meeting_visible`; a project chunk
against `project_service.ensure_project_visible` (the same function Phase 7
Stage 1's own Codex-caught P1 already taught this project to reuse
correctly); leads and tasks pass straight through, since RBAC.md already
documents both as org-wide with no ownership-split.

**No AI-derived value is written into another module's existing columns.**
`MeetingSummary`, and later `LeadScore`/`ProjectRiskAssessment`, each get
their own table under `ai`, holding a plain reference into the owning
module's row — the same shape `DocumentReference` already uses. The one
schema change to an existing module (`MeetingAction.source`, Stage 2) is
authored as a normal `meetings`-owned migration, not an `ai`-owned write.

**Tests never call the real API.** `AIClient` is a `Protocol` (`complete()`,
`embed()` from Stage 3); `get_ai_client()` is a lazy-initialized dependency
mirroring `platform/email/deps.py`'s `get_email_sender` exactly, and every
test overrides it with a deterministic `FakeAIClient` via a `fake_ai_client`
fixture (same shape as `fake_email_sender`/`fake_verifier`). A missing
`OPENAI_API_KEY` fails only an actual real-provider call, never app boot —
the same lazy-init posture `FIREBASE_CREDENTIALS` already has.

## Alternatives rejected

**Anthropic, or a provider-agnostic abstraction picking a vendor later.**
Rejected by explicit product-owner decision — OpenAI is the one integration
this phase builds, and an abstraction layer for a second vendor nobody has
asked to add would be exactly the kind of speculative infrastructure
ADR-0010's own minimal-footprint philosophy argues against.

**A background worker for embedding generation.** Considered because
re-embedding stale rows on every retrieval call adds latency to that
request. Rejected for V1: this project's data volume is small enough that a
bounded per-call batch (`reindex_stale`, capped at a small `max_sources`)
keeps the index eventually-fresh without a queue, a cron, or write-hooks
threaded through four other modules — see ADR-0010's own reasoning, unchanged.

**Filtering retrieval by a cached visibility/role column on the chunk
row.** Faster to query, but wrong: a project's membership (or a meeting's
participant list) can change after the chunk was indexed, and caching
"who could see this when it was embedded" is exactly the kind of stale
permission check Phase 7 Stage 1's Codex review already flagged this
project for getting wrong once. Re-validating live against the source
module's real rule costs one extra lookup per candidate and is never wrong.

## Consequences

- One new server-side secret: `OPENAI_API_KEY`. Never in the repository,
  never in an image, never in a `NEXT_PUBLIC_*` variable — the browser never
  talks to OpenAI directly.
- `pgvector` is a new Postgres extension (added Stage 3), the first
  extension this project has added since `citext` in the initial migration.
  Unlike `citext`, it is **not** a "trusted" extension — only a superuser
  can install it, so (confirmed directly against a real Postgres, not
  assumed) `trinol_migrator` cannot run `CREATE EXTENSION vector` itself
  despite owning the database. `docker-compose.yml` and CI both switch
  from `postgres:16-alpine` to `pgvector/pgvector:pg16` (a drop-in
  `postgres:16` with pgvector built in), and
  `infrastructure/postgres/init.sql` — which already runs as a superuser
  at provisioning time, before any migration — installs the extension
  there. The migration itself keeps its own `CREATE EXTENSION IF NOT
  EXISTS vector` for documentation/idempotency, but it is always a no-op
  by the time it runs. Production's managed Postgres needs an admin to
  enable the extension the same way (DEPLOYMENT.md §7).
- Every AI feature this phase adds is additive and advisory — none of them
  change what an existing route returns for non-AI data, and none of them
  are on any existing request's hot path (they are their own new routes,
  triggered by their own new user actions).
- A phase-level cost/latency sanity pass on `reindex_stale`'s bounded batch
  size is part of Stage 8's closing audit, not deferred indefinitely.
