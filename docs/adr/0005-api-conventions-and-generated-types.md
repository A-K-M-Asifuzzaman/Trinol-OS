# ADR-0005 — REST conventions and generated TypeScript types

Status: Accepted (Phase 0)

## Context

Two applications in one repository need a type contract. MASTER_PROMPT §5
suggests `packages/shared`; §34 fixes the error envelope.

## Decision

**REST**, versioned at `/api/v1/`, plural resource nouns, UUIDv7 path ids.

- Lists: `?limit=&offset=&sort=&q=` plus per-resource filters. `limit` default
  50, hard cap 200. Response `{"items": [...], "total": n}`.
- Errors always use the §34 envelope with a stable machine-readable `code`, a
  human `message`, the `request_id`, and optional `details` for field errors.
- `404` — not `403` — for anything belonging to another organization.
- All timestamps ISO-8601 UTC with `Z`. All money as a decimal **string** plus a
  `currency` field; never a float in JSON.
- Breaking changes mean `/api/v2`, and both are served during migration.

**Types**: FastAPI emits OpenAPI; `openapi-typescript` generates
`apps/web/lib/api/types.gen.ts`. The file is committed, and CI regenerates it
and fails on a diff — so a backend change that breaks the frontend contract
fails at build time rather than in the browser.

## Alternatives rejected

**`packages/shared` with hand-written types.** Two hand-maintained definitions
of the same contract, kept in sync by discipline. Generation removes the class
of bug entirely.

**GraphQL.** Solves over-fetching for many diverse clients. There is one client,
rendered largely on the server.

**tRPC.** Requires a TypeScript backend.

**Cursor pagination in V1.** Deferred. Deep offsets hurt at scale this product
does not have; keyset pagination is contained inside the list helper when it is
needed. `ponytail: offset pagination; switch to keyset when a list exceeds
~50k rows.`

## Consequences

- One source of truth for the contract, enforced by CI.
- Every route is documented for free at `/docs`.
- The generated file must be regenerated in any PR that changes a schema; the
  CI diff check makes forgetting impossible rather than merely embarrassing.
