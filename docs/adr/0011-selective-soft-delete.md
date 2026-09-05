# ADR-0011 — Soft delete only where the product needs history

Status: Accepted (Phase 0)

## Context

The reflex on a business application is a global `deleted_at` mixin on every
table.

## Decision

`archived_at` on exactly four entities: `projects`, `clients`, `leads`,
`invoices`. Everything else is a hard delete, with the deletion recorded as an
audit event.

These four are the entities that appear in historical reporting and in
relationships that must not dangle: a client with paid invoices cannot be
erased, a lost lead is conversion-rate data, an invoice is a financial record
(and is *cancelled*, never deleted — see ADR-0007).

## Alternatives rejected

**Global soft delete.** Every query for the rest of the product's life must
remember `WHERE deleted_at IS NULL`, and the one that forgets shows deleted rows
to users. Unique constraints stop working as intended (a deleted row still
occupies its unique key). Foreign keys lose their meaning. It is a large,
permanent tax paid for an undo feature nobody asked for.

**No soft delete at all.** Deleting a client would cascade into invoices, which
is unacceptable for financial history.

## Consequences

- Only four tables carry the "did you filter it?" burden, and each has an
  explicit test that the list endpoint excludes archived rows.
- Deleting a task, comment or checklist item really deletes it. The audit event
  keeps the record of who did it and when.
- Restoring an archived entity is a one-field update; there is no
  general-purpose trash UI, and none is planned.
