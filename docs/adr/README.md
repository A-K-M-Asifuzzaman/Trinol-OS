# Architecture Decision Records

One file per decision. A record is written when a choice is hard to reverse,
costly to revisit, or likely to be questioned later. Superseded records are kept
and marked, never deleted.

| # | Decision | Status |
|---|---|---|
| [0001](0001-monorepo-and-stack.md) | Monorepo layout and stack; no shared package | Accepted |
| [0002](0002-opaque-server-sessions.md) | Opaque server-side sessions instead of JWT | Accepted, amended by 0013 |
| [0003](0003-single-db-org-scoping.md) | Organization isolation via a scoped-session choke point | Accepted |
| [0004](0004-roles-as-code.md) | Roles and permissions as code, not database rows | Accepted |
| [0005](0005-api-conventions-and-generated-types.md) | REST conventions and generated TypeScript types | Accepted |
| [0006](0006-single-append-only-activity-table.md) | One append-only table for activity and audit | Accepted |
| [0007](0007-money-and-invoice-totals.md) | Money representation and invoice arithmetic | Accepted |
| [0008](0008-file-storage.md) | File storage abstraction | Accepted |
| [0009](0009-deployment-single-host-compose.md) | Single-host Docker Compose deployment | Accepted |
| [0010](0010-no-redis-or-worker-in-v1.md) | No Redis and no background worker in V1 | Accepted |
| [0011](0011-selective-soft-delete.md) | Soft delete only where the product needs history | Accepted |
| [0012](0012-v1-scope-trims.md) | Deliberate V1 scope trims | Accepted |
| [0013](0013-firebase-as-identity-provider.md) | Firebase Authentication as identity provider, local sessions | Accepted |
| [0014](0014-ai-openai-and-pgvector.md) | OpenAI provider, synchronous calls, finance never embedded | Accepted |
