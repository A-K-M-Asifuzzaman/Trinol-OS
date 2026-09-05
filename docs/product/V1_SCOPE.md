# Trinol OS — V1 Scope

V1 is the version TrinolIT uses every day to run the company. It is finished
when the eleven questions in MASTER_PROMPT §2 can be answered by opening the
dashboard.

## In V1

**Foundation** — invited users, one organization, four roles, session auth, app
shell, dashboard.

**Work** — projects with client, owner, dates, budget and health; tasks with
status, priority, assignee, due date, tags; Kanban with drag-and-drop; milestones;
comments; checklists; attachments; My Work.

**Sales** — leads with source, service, value, stage and follow-up date;
pipeline board; clients with a profile view; lead → client + project conversion;
the public contact endpoint for trinolit.com with notification and confirmation
email.

**Meetings** — schedule, participants, notes, decisions, action items, and
promoting an action item to a task.

**Finance** — income, expenses by category, invoices with line items and PDF
export, payments, and a finance overview. Visible to ADMIN and OWNER only.

**Cross-cutting** — activity feed, audit log, in-app notifications, document
links, command palette (⌘K), global search over projects, tasks, clients, leads
and people.

## Not in V1

The full list with reasoning is [ADR-0012](../adr/0012-v1-scope-trims.md).
Headlines: no AI, no Google Calendar or Drive integration, no client portal, no
time tracking or timesheets, no multi-currency, no self-signup, no custom roles,
no mobile app.

## Quality bar

A feature is not shipped because a page renders. Per
[AGENTS.md](../../AGENTS.md), it needs UI, backend, validation, authorization,
persistence, error handling, loading and empty states, responsive behaviour,
tests, and passing lint/typecheck/build.

Two additions that apply to every screen:

- **Four states, always** — loading, empty, error, populated. An empty state
  says what the thing is and offers the action that creates the first one.
- **Answer the question fast** — every page exists to answer one question. If
  the primary answer is not visible without scrolling on a laptop, the page is
  not done.

## Success criteria

V1 is done when, for four consecutive weeks, TrinolIT runs its projects, tasks,
leads and invoices in Trinol OS and does not fall back to a spreadsheet.
