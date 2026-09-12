# Trinol OS — Database Design

PostgreSQL 16. SQLAlchemy 2 (async, `asyncpg`). Alembic for migrations.

## 1. Conventions

- **Primary keys**: UUIDv7 (`uuid` column type), generated in the application.
  Time-ordered, so index locality is fine and ids are not guessable.
- **Timestamps**: `created_at`, `updated_at` — `timestamptz`, default `now()`.
  All times stored UTC. `updated_at` maintained by a trigger, not by the ORM,
  so a raw SQL fix cannot silently skip it.
- **Soft delete**: only where the product needs history — `projects`, `clients`,
  `leads`, `invoices` get `archived_at`. Everything else is a hard delete.
  No global soft-delete mixin ([ADR-0011](../adr/0011-selective-soft-delete.md)).
- **Enums**: PostgreSQL native enum types, mirrored by Python `StrEnum`.
  Adding a value is a migration; that friction is intentional.
- **Money**: `NUMERIC(14,2)` + a 3-letter `currency` column. Never float.
  See [ADR-0007](../adr/0007-money-and-invoice-totals.md).
- **Naming**: snake_case, plural tables, `<table>_id` FKs, explicit constraint
  names (`ck_`, `uq_`, `fk_`, `ix_`) so migrations are readable.
- Every FK has an index unless it is already the left prefix of a composite one.

## 2. Entity relationship overview

```
Organization 1─┬─* Membership *─1 User
               ├─* Client   1─* Project
               ├─* Lead     ─(convert)→ Client + Project
               ├─* Project  1─┬─* Task 1─┬─* TaskComment
               │              │          ├─* TaskChecklistItem
               │              │          └─* TaskAttachment ─1 FileObject
               │              ├─* Milestone
               │              └─* ProjectMember *─1 User
               ├─* Meeting  1─┬─* MeetingParticipant *─1 User
               │              ├─* MeetingDecision
               │              └─* MeetingAction ─(promote)→ Task
               ├─* Invoice  1─┬─* InvoiceItem
               │              └─* Payment
               ├─* Income
               ├─* Expense
               ├─* DocumentReference
               ├─* ActivityEvent
               ├─* Notification
               └─* ContactSubmission ─(creates)→ Lead

User 1─* Session
```

## 3. Tables

### identity

**organizations** — `id`, `name`, `slug` (uq), `logo_file_id?`, timestamps.
`logo_file_id` needs the §5.1 treatment even though this table has no
`organization_id` column: its own `id` **is** the tenant key, so the constraint
is `FOREIGN KEY (id, logo_file_id) REFERENCES file_objects (organization_id, id)`,
which makes an organization pointing at another organization's file impossible.
`ON DELETE RESTRICT`, not `SET NULL`: on a composite FK, Postgres nulls
*every* referencing column on the cascade action, not just `logo_file_id` —
here that includes `id`, the primary key, which can never be null. (Found
during Phase 2 Stage 1 review, same bug shape as `tasks.milestone_id`.) A
missing logo is still meant to be cosmetic, so the service clears
`logo_file_id` itself before deleting a `file_objects` row currently in use
as a logo, rather than relying on the FK to do it.

**users** — `id`, `firebase_uid` (uq), `email` (**citext**, globally unique),
`auth_provider` (`PASSWORD|GOOGLE`), `full_name`, `avatar_url?`,
`last_login_at?`, timestamps.
`avatar_url` is a plain URL, not a `file_objects` FK: `users` is global while
`file_objects` is org-scoped, so an FK there would be the one cross-tenant
reference §5.1 cannot express. Google sign-in supplies a photo URL for free,
and this removes the avatar upload path entirely.
A user is global; organization access comes only from `memberships`.
No `password_hash` — credentials live in Firebase
([ADR-0013](../adr/0013-firebase-as-identity-provider.md)). `firebase_uid` is
the join key; `email` is a refreshed cache for display and invitation matching,
because addresses change.

**memberships** — `id`, `organization_id`, `user_id`, `role`
(`OWNER|ADMIN|MANAGER|MEMBER`), `job_title?`, `status`
(`ACTIVE|ON_LEAVE|INACTIVE`), `joined_at`, timestamps.
- `uq_membership_org_user (organization_id, user_id)`
- Partial unique index guaranteeing an org can never lose its last owner is not
  expressible; enforced in `identity.services` under `SELECT … FOR UPDATE` on
  the org row, with a regression test. See [RBAC.md §5](RBAC.md#5-escalation-guards).

**sessions** — `id`, `user_id`, `organization_id`, `token_hash` (sha256, uq),
`csrf_token`, `user_agent`, `ip`, `expires_at`, `last_seen_at`, `revoked_at?`.
`csrf_token` is stored in **plaintext**, unlike `token_hash` — AUTH.md §6
requires the raw value back from `GET /api/v1/auth/session`, impossible from
a one-way hash, and its security comes from the browser's same-origin policy
rather than secrecy at rest (standard for double-submit CSRF tokens; Phase 1
Stage 5 caught and corrected an earlier `csrf_hash` naming/design that
couldn't actually satisfy this).
Detail in [AUTH.md](AUTH.md).

**invitations** — `id`, `organization_id`, `email`, `role`, `token_hash` (uq),
`invited_by`, `expires_at`, `accepted_at?`. Phase 1.

### work

**projects** — `id`, `organization_id`, `project_code`, `name`, `description?`,
`client_id?`, `status` (`PLANNING|ACTIVE|ON_HOLD|COMPLETED|CANCELLED`),
`health` (`ON_TRACK|AT_RISK|DELAYED`), `owner_id`, `start_date?`, `deadline?`,
`budget?`, `currency`, `repository_url?`, `production_url?`, `staging_url?`,
`archived_at?`, timestamps.
- `uq_project_org_code (organization_id, project_code)`
- `uq_projects_org_id (organization_id, id)` — required by composite FKs from
  `tasks`, `milestones`, `meetings`, `income`, `invoices`,
  `document_references.project_id` (§5.1)
- `ck_project_dates (deadline IS NULL OR start_date IS NULL OR deadline >= start_date)`
- `progress` is **derived** (done tasks / total tasks), computed on read.
  Not stored — a stored copy is a cache that goes stale on every task write.

**project_members** — `id`, `organization_id`, `project_id`, `user_id`, `role_on_project`,
`added_at`. `uq (project_id, user_id)`.

**milestones** — `id`, `organization_id`, `project_id`, `name`, `description?`,
`due_date?`, `completed_at?`, `position`.
- `uq_milestones_org_id (organization_id, id)` — required by `tasks.milestone_id` (§5.1)

**tasks** — `id`, `organization_id`, `project_id?`, `title`, `description?`,
`status` (`TODO|IN_PROGRESS|REVIEW|DONE|CANCELLED`),
`priority` (`LOW|MEDIUM|HIGH|URGENT`), `assignee_id?`, `created_by`,
`milestone_id?`, `due_date?`, `start_date?`, `estimated_hours?`,
`actual_hours?`, `tags text[]`, `board_position numeric`, `completed_at?`,
timestamps.
- One assignee, not a join table — the spec's task fields list a single
  `assignee_id`. A `task_assignees` table is speculative ([ADR-0012](../adr/0012-v1-scope-trims.md)).
- `board_position` is a `numeric` sort key so a drag reorders one row instead of
  renumbering a column. `ponytail: fractional indexing, rebalance job if
  precision is ever exhausted.`
- `ix_tasks_org_status_due (organization_id, status, due_date)`,
  `ix_tasks_org_assignee_status (organization_id, assignee_id, status)`,
  `ix_tasks_project (project_id)`.
- `ck_task_completed (status <> 'DONE' OR completed_at IS NOT NULL)`.
- `uq_tasks_org_id (organization_id, id)` — required by composite FKs from
  `task_comments`, `task_checklist_items`, `task_attachments`,
  `meeting_actions.task_id` (§5.1)

**task_comments** — `id`, `organization_id`, `task_id`, `author_id`, `body`,
`edited_at?`, timestamps.

**task_checklist_items** — `id`, `organization_id`, `task_id`, `label`,
`done`, `position`.

**task_attachments** — `id`, `organization_id`, `task_id`, `file_id`,
`uploaded_by`, `created_at`.

### crm

**clients** — `id`, `organization_id`, `name`, `company?`, `email?`, `phone?`,
`website?`, `address?`, `notes?`, `status`, `owner_id?`, `archived_at?`, timestamps.
- `uq_clients_org_id (organization_id, id)` — required by composite FKs from
  `projects.client_id`, `leads.converted_client_id`, `meetings.client_id`,
  `income.client_id`, `invoices.client_id`, `document_references.client_id` (§5.1)

**leads** — `id`, `organization_id`, `name`, `company?`, `email?`, `phone?`,
`source` (`WEBSITE|FACEBOOK|LINKEDIN|REFERRAL|EMAIL|PHONE|OTHER`), `service?`,
`estimated_value?`, `currency`, `stage`
(`NEW|CONTACTED|MEETING|PROPOSAL|NEGOTIATION|WON|LOST`), `assigned_to?`,
`next_follow_up?`, `notes?`, `converted_client_id?`, `converted_at?`,
`lost_reason?`, `board_position numeric`, `archived_at?`, timestamps.
- `ix_leads_org_stage (organization_id, stage)`,
  `ix_leads_org_followup (organization_id, next_follow_up)`.
- `ck_lead_contact (email IS NOT NULL OR phone IS NOT NULL)`.
- `uq_leads_org_id (organization_id, id)` — required by
  `lead_stage_events.lead_id`, `contact_submissions.lead_id` (§5.1)

**lead_stage_events** — `id`, `organization_id`, `lead_id`, `from_stage?`,
`to_stage`, `actor_id?`, `created_at`. Pipeline history, needed for conversion
analytics in Phase 7. Written in the same transaction as the stage change.

**contact_submissions** — `id`, `organization_id`, `name`, `email`, `phone?`,
`company?`, `service?`, `budget?`, `message`, `ip`, `user_agent`,
`reference_number` (uq per org), `lead_id?`, `spam_score?`, `created_at`.
Raw inbound record, kept even when the lead is later deleted.
The endpoint is unauthenticated, so there is no session to take
`organization_id` from: it comes from configuration (`PUBLIC_CONTACT_ORG_SLUG`),
resolved once at startup and failing the boot if it does not exist. This is the
single org-scoped write with no session behind it, and it is why the value is
config rather than anything the caller can influence.

### meetings

**meetings** — `id`, `organization_id`, `title`, `description?`, `starts_at`,
`ends_at`, `client_id?`, `project_id?`, `meeting_url?`, `location?`, `notes?`,
`external_event_id?`, `created_by`, timestamps.
`ck_meeting_times (ends_at > starts_at)`.
`uq_meetings_org_id (organization_id, id)` — required by composite FKs from
`meeting_participants`, `meeting_decisions`, `meeting_actions`,
`document_references.meeting_id` (§5.1)

**meeting_participants** — `id`, `organization_id`, `meeting_id`, `user_id?`,
`external_email?`, `response`. `ck` exactly one of `user_id` / `external_email`.

**meeting_decisions** — `id`, `organization_id`, `meeting_id`, `body`,
`decided_by?`, `created_at`.

**meeting_actions** — `id`, `organization_id`, `meeting_id`, `description`,
`owner_id?`, `due_date?`, `task_id?` (set once promoted), `created_at`.

### finance

See [ADR-0007](../adr/0007-money-and-invoice-totals.md) for the arithmetic rules.

**income** — `id`, `organization_id`, `amount`, `currency`, `source`,
`client_id?`, `project_id?`, `invoice_id?`, `received_on` (date),
`payment_method`, `reference?`, `notes?`, `created_by`, timestamps.

**expenses** — `id`, `organization_id`, `amount`, `currency`, `category`
(enum, 10 values per spec §19), `description`, `vendor?`, `spent_on` (date),
`payment_method`, `receipt_file_id?`, `notes?`, `created_by`, timestamps.

**invoices** — `id`, `organization_id`, `invoice_number`, `client_id`,
`project_id?`, `issue_date`, `due_date`, `currency`, `subtotal`,
`discount_amount`, `tax_amount`, `total`, `amount_paid`, `status`
(`DRAFT|SENT|PARTIALLY_PAID|PAID|CANCELLED`), `notes?`, `terms?`,
`sent_at?`, `created_by`, `archived_at?`, timestamps.
- `uq_invoice_org_number (organization_id, invoice_number)` — the hard guarantee
  against duplicate numbers.
- `uq_invoices_org_id (organization_id, id)` — required by composite FKs from
  `invoice_items`, `payments`, `income.invoice_id` (§5.1)
- `ck_invoice_amounts (subtotal >= 0 AND discount_amount >= 0 AND tax_amount >= 0
   AND total >= 0 AND amount_paid >= 0)`
- `ck_invoice_total (total = subtotal - discount_amount + tax_amount)` — the
  arithmetic invariant lives in the database, not only in Python.
- `ck_invoice_dates (due_date >= issue_date)`
- `OVERDUE` is **not** a stored transition written by a cron job; it is derived
  on read from `status IN (SENT, PARTIALLY_PAID) AND due_date < today`. One less
  scheduled job to run and to get wrong.

**invoice_items** — `id`, `organization_id`, `invoice_id`, `description`,
`quantity NUMERIC(12,3)`, `unit_price`, `line_total`, `position`.
`ck_line_total (line_total = round(quantity * unit_price, 2))`.

**payments** — `id`, `organization_id`, `invoice_id`, `amount`, `currency`,
`paid_on`, `method`, `reference?`, `recorded_by`, `created_at`.
`ck_payment_positive (amount > 0)`.

**invoice_counters** — `organization_id`, `year`, `last_seq`. PK
`(organization_id, year)`. Number generation takes `SELECT … FOR UPDATE` on this
row, so two concurrent invoices cannot produce `TRI-2026-0001` twice.

### documents

**document_references** — `id`, `organization_id`, `title`, `url`, `kind`
(enum: `GOOGLE_DRIVE|GITHUB|OTHER`, Phase 6), `project_id?`, `client_id?`,
`meeting_id?`, `added_by`, timestamps.
A plain external-link table, not a `file_objects` wrapper — Phase 6/
[ADR-0012](../adr/0012-v1-scope-trims.md): "V1 stores external links" for
Google Drive; GitHub and other systems get the same treatment via `kind`.
No OAuth, no file upload. `project_id`/`client_id`/`meeting_id` are each
independently optional and not mutually exclusive — a reference may have
none, one, or more than one parent set; a parent-less row is a general
org-wide link. No unique constraint of its own (nothing composite-FKs to
a `document_references` row). No `archived_at` — not one of ADR-0011's
four soft-deleted entities, so deletion is a hard delete with an audit
event.

Owned by its own `documents` module, not `platform`
([ARCHITECTURE.md §3](ARCHITECTURE.md#3-domain-modules)) — validating the
optional parent ids means calling into `work`/`crm`/`meetings` services,
and `platform` may never import a domain module (Codex Phase 6 Stage 2
P1).

### ai

Phase 8. Owned by its own `ai` module, not `platform`
([ARCHITECTURE.md §3](ARCHITECTURE.md#3-domain-modules)) — same reasoning
as `documents`: retrieval/summarization/scoring need to call into
`work`/`crm`/`meetings`/`finance` services, and `platform` may never import
a domain module. Grows across Phase 8's stages; this stage adds:

**meeting_summaries** — `id`, `organization_id`, `meeting_id` (uq — 1:1,
regenerated in place, not versioned), `content` (text), `model` (text,
which `OPENAI_CHAT_MODEL` produced it), `generated_by` (→ memberships),
timestamps. Visibility is the meeting's own (`ensure_meeting_visible`) —
no separate permission, no ownership-split of its own.

### platform

**activity_events** — `id`, `organization_id`, `actor_id?`, `event` (text),
`entity_type`, `entity_id`, `metadata jsonb`, `is_audit bool`, `ip?`,
`created_at`.
One table serves both the §21 activity feed (`is_audit = false`) and the §28
audit log (`is_audit = true`). Append-only: the application database role is
granted `INSERT, SELECT` and **not** `UPDATE, DELETE`
([ADR-0006](../adr/0006-single-append-only-activity-table.md)).

That grant is only real if the application connects as a role other than the
table's owner — Postgres lets an owner bypass its own grants, the same fact
ADR-0003 notes about RLS. So there are **two roles in every environment,
including local and CI, not just production**: `trinol_migrator` owns every
object and is what `DATABASE_MIGRATION_URL` / Alembic connects as; `trinol_app`
is the runtime role or `DATABASE_URL` connects as, and is the one actually
`REVOKE`d from `UPDATE, DELETE` on this table. The migration that creates
`activity_events` also does the revoke, and `ALTER DEFAULT PRIVILEGES` grants
`trinol_app` the normal set on every table `trinol_migrator` creates
afterward, so later migrations don't need to repeat the grant.
- `ix_activity_org_created (organization_id, created_at DESC)`,
  `ix_activity_entity (organization_id, entity_type, entity_id)`.

**notifications** — `id`, `organization_id`, `user_id`, `type`, `title`,
`body?`, `link?`, `read_at?`, `created_at`.

**file_objects** — `id`, `organization_id`, `storage_key` (uq), `filename`,
`content_type`, `size_bytes`, `checksum_sha256`, `uploaded_by`, `created_at`.
- `uq_file_objects_org_id (organization_id, id)` — required by the composite FKs
  from `organizations.logo_file_id`, `expenses.receipt_file_id` and
  `task_attachments.file_id` (§5.1).
Storage abstraction in [SECURITY.md §6](SECURITY.md#6-file-uploads).

**rate_limit_buckets** — `key` (pk), `window_start`, `count`. Postgres-backed
fixed-window limiter for the public contact endpoint and login.
Counters are updated with one atomic `INSERT ... ON CONFLICT DO UPDATE`
statement; callers never read, increment and write a bucket in separate
statements.
`ponytail: fixed window in Postgres; move to Redis sliding window if the public
endpoint ever sees real traffic.`

## 4. Migrations

- Alembic, one migration per merged change, autogenerate then **hand-review**
  (autogenerate misses enum changes, check constraints and index renames).
- Every migration must be reversible or explicitly declare why it is not.
- CI runs `alembic upgrade head` against an empty database **and**
  `alembic downgrade -1 && alembic upgrade head` to catch broken downgrades.
- CI fails if the ORM metadata and the migration head diverge
  (`alembic check`).
- Data migrations never run in the same revision as a destructive schema change.

## 5. Organization isolation

Single database, single schema, `organization_id` on every business table.
Isolation is enforced in the application at one choke point, not by scattering
`WHERE organization_id = …` across services
([ADR-0003](../adr/0003-single-db-org-scoping.md)):

1. All org-scoped models inherit `OrgScoped`, which carries the FK.
2. Services never receive a bare `AsyncSession`. They receive `OrgSession`, a
   thin wrapper whose `select()` helper injects the org filter and whose
   `add()` stamps `organization_id`.
3. A SQLAlchemy `before_execute` guard raises if a statement touches an
   `OrgScoped` table without an `organization_id` predicate. It is **on in all
   environments**, not just tests — the cost is one AST walk per statement and
   it turns a silent data leak into a 500.
4. A cross-org isolation test matrix runs every org-scoped endpoint as a member
   of org B against a resource in org A and asserts `404`.

### 5.1 Cross-organization relationship integrity

Every foreign key from one organization-owned table to another must be a
composite foreign key containing both `organization_id` and the referenced id.
A task's `(organization_id, project_id)` references the project's corresponding
pair. This applies to nullable references and join tables. Migration tests
deliberately attempt cross-organization references and assert that PostgreSQL
rejects them.

**The referenced table must carry the matching unique constraint.** PostgreSQL
will not accept a composite FK unless a unique constraint exists on exactly
those columns in that order — a composite FK to a table that only has a primary
key on `id` fails at migration time, not at review time.

So every org-scoped table that is the target of a composite FK declares:

```sql
UNIQUE (organization_id, id)
```

which today means `projects`, `clients`, `tasks`, `milestones`, `meetings`,
`invoices`, `leads` and `file_objects` — each listed with its constraint name
and the columns that depend on it in §3. Any new org-scoped table that acquires
a child gets this in the same migration that adds the child.

This constraint is redundant for *uniqueness* — `id` alone is already unique —
and exists solely to satisfy the FK requirement. It costs one additional index
per table, which is the price of having PostgreSQL enforce tenant integrity
instead of trusting the service layer. Do not let a reviewer or an autogenerated
migration remove it as dead weight; a comment on each constraint says why it is
there.

The person-reference rule below uses `memberships`, which already has
`uq_membership_org_user (organization_id, user_id)` — the required constraint
exists for the same reason and needs no addition.

**References to people are composite too.** `users` is global, so a plain
`assignee_id → users.id` would happily let a task in org A be assigned to
someone who has never been a member of it — their name then renders in our UI
and they receive notifications about work they cannot see. Leaving that to the
service layer contradicts the reason this rule exists.

So every column naming a person inside an organization references the
**membership**, not the user:

```sql
FOREIGN KEY (organization_id, assignee_id)
  REFERENCES memberships (organization_id, user_id)
```

with `UNIQUE (organization_id, user_id)` on `memberships` — an index that
already exists. This covers `tasks.assignee_id`, `tasks.created_by`,
`projects.owner_id`, `project_members.user_id`, `leads.assigned_to`,
`clients.owner_id`, `meeting_participants.user_id`, `task_comments.author_id`,
`payments.recorded_by` and every other actor column on an org-scoped row.

`sessions` follows the same rule: `(organization_id, user_id)` references
`memberships`, which makes a session for a non-member structurally impossible
rather than merely checked at login.

Two deliberate exceptions, both because the row must outlive the membership:
`activity_events.actor_id` and `invitations.invited_by` reference `users`
directly. History must not disappear when someone leaves, and `ON DELETE` on a
membership must not cascade into the audit trail.

### 5.2 Membership deletion semantics

**A membership row is never deleted by any product flow.** Removing someone from
the organization sets `status = INACTIVE`, which
[AUTH.md §7](AUTH.md#7-session--organization) already rejects at authentication
time. The row stays, so every FK pointing at it stays valid and every past
assignment, comment and payment remains attributable.

This is not a new soft-delete column — `memberships.status` already exists — so
it does not contradict [ADR-0011](../adr/0011-selective-soft-delete.md).

Referential actions, chosen so that an *unexpected* delete fails loudly rather
than silently damaging data:

| Referencing column | Action | Why |
|---|---|---|
| `tasks.assignee_id`, `projects.owner_id`, `clients.owner_id`, `leads.assigned_to`, `meeting_participants.user_id` | `ON DELETE RESTRICT` | Nullable, but `SET NULL` would silently erase who owned the work. Deactivation, not deletion, is the supported path. |
| `tasks.created_by`, `task_comments.author_id`, `payments.recorded_by`, `meetings.created_by`, and every other authorship column | `ON DELETE RESTRICT` | Non-nullable by design — attribution is the point. There is no correct automatic behaviour here. |
| `project_members.user_id` | `ON DELETE CASCADE` | A project membership for a non-member is meaningless. |
| `sessions.(organization_id, user_id)` | `ON DELETE CASCADE` | A session without a membership is garbage; cascading is the correct cleanup. |

`ON UPDATE` needs no action anywhere: `organization_id` and `user_id` are
immutable once written.

**Deactivation is not silent.** When a membership goes `INACTIVE`, the service
revokes that user's sessions and returns the count of open items still assigned
to them, so the UI can prompt for reassignment. Nothing is auto-reassigned or
auto-nulled — losing that information is worse than showing an inactive name.

**Genuine erasure** (a GDPR request) is an operator procedure, not a product
feature: anonymize the global `users` row — clear `full_name`, `email`,
`avatar_url`, `firebase_uid` — and leave `memberships` and history intact. The
identity disappears; the referential graph does not. This is documented rather
than built, because it has never been asked for.
`ponytail: manual procedure; build it when someone actually requests erasure.`

Postgres RLS is the stronger answer and is deliberately deferred to the
multi-tenant SaaS phase; the schema is already shaped for it.
