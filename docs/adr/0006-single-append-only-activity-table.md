# ADR-0006 — One append-only table for activity and audit

Status: Accepted (Phase 0)

## Context

MASTER_PROMPT §21 wants a user-facing activity feed. §28 wants an audit log of
sensitive actions that is "not casually editable". The two have identical
shape: actor, event, entity type, entity id, metadata, timestamp.

## Decision

One table, `activity_events`, with an `is_audit boolean` column. The feed reads
`is_audit = false`; the audit view (`ADMIN+` only) reads `is_audit = true`.

Immutability is enforced by the **database**, not by convention: the application
role is granted `INSERT, SELECT` on the table and is not granted `UPDATE` or
`DELETE`. An accidental (or malicious) edit through the application fails at the
database, which is what "not casually editable" has to mean to be worth
anything.

Events are written inside the same transaction as the change they describe, so
the log can never disagree with the data.

## Alternatives rejected

**Two tables.** The columns are the same; the only differences are visibility
and retention, and both are one predicate. Two tables means two writers, two
query paths, and the ongoing question of which one a new event belongs in — and
in practice, events that belong in both.

**Event sourcing.** A different architecture for a different problem.

**Application-level immutability only.** Discipline is not a control.

## Consequences

- One writer helper: `record(event, entity, *, audit=False, metadata=...)`.
- Retention differs by flag: feed rows can be pruned after N months, audit rows
  are never pruned. One `DELETE` with a predicate — but it must be run by a
  maintenance role, since the application role cannot delete. That friction is
  the point.
- The table grows monotonically. Indexed on `(organization_id, created_at DESC)`
  and `(organization_id, entity_type, entity_id)`; partitioning by month is the
  documented escape hatch and is not needed for years.
  `ponytail: single table; partition by month if it passes ~50M rows.`
