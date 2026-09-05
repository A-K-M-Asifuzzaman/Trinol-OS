# ADR-0012 — Deliberate V1 scope trims

Status: Accepted (Phase 0)

## Context

MASTER_PROMPT §25 offers a candidate entity list and §1 warns "do not build an
enormous ERP in V1". Phase 0's job includes identifying overengineering. These
are the things the specification implies that V1 will **not** build, recorded so
they are omissions by decision rather than by accident.

## Trimmed

| Item | From | Why not now | When |
|---|---|---|---|
| `Role`, `Permission` tables | §25 | Nothing configures custom roles (ADR-0004) | V4 |
| `TaskAssignee` join table | §25 | §9 defines a single `assignee_id`; multi-assignee is speculative | when asked |
| `RefreshSession` | §25 | No JWT, so no refresh tokens (ADR-0002) | never |
| `packages/shared` | §5 | Types are generated (ADR-0005) | if a second client appears |
| Redis, worker, cache | §4 | No load to justify them (ADR-0010) | on the triggers in ADR-0010 |
| Public self-signup | — | Internal tool; users are invited | V4 |
| Multi-currency + FX | §19 | One currency per org; column exists for later | when a client bills in another currency |
| Stored `progress`, stored `OVERDUE` | §10, §20 | Derived on read; no job to run or to get wrong | if the query ever costs anything |
| Nightly reminder jobs | §22 | Notifications start in-app, computed on read | Phase 2+ |
| Presigned direct uploads | §24 | Proxied uploads are simpler and validate before storing (ADR-0008) | on the trigger in ADR-0008 |
| Google Calendar / Drive | §15, §16 | Explicitly V2 in the spec; V1 stores external links | V2, if justified |
| Full-text / semantic search | §23 | Command palette searches by prefix over indexed columns | Postgres FTS when it stops feeling instant |
| Any LLM feature | §30 | §30 says V1 must not depend on one | Phase 8 |
| Two-factor authentication | — | Available as a Firebase setting (ADR-0013), not built by us | flip it on when wanted |

## Ambiguities raised rather than silently resolved

These need a human decision and are listed in the Phase 0 report:

1. **Hosting target** — ADR-0009 assumes one VM; a PaaS split would change the
   same-origin cookie assumption in ADR-0002.
2. **Tax model for invoices** — a single tax rate per invoice is assumed. Per-line
   tax, VAT/GST registration numbers and tax-inclusive pricing are not built.
3. **Google Calendar** — §15 says "prepare architecture", §39 Phase 4 says
   "if justified". Treated as not justified until asked.
4. **Time tracking** — tasks carry `estimated_hours` / `actual_hours` as plain
   numbers. No timer, no timesheet, no billable-hours → invoice link.
5. **Client portal** — no external-user access anywhere in the spec; the role
   model has no place for one, by design.

## Consequences

Every trim above is additive later. None of them require reshaping the schema,
the auth model or the module boundaries — which was the constraint they were
chosen against.
