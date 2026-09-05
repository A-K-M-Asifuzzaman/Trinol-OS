# ADR-0010 — No Redis and no background worker in V1

Status: Accepted (Phase 0)

## Context

MASTER_PROMPT §4 lists "Redis only where needed". The usual reflexes are a cache,
a rate limiter, and a Celery/RQ worker for email and scheduled jobs.

## Decision

Neither is introduced in V1.

- **Rate limiting** → a `rate_limit_buckets` table in PostgreSQL, fixed window,
  updated by one atomic `INSERT ... ON CONFLICT DO UPDATE` statement. The
  endpoints that need it (login, password reset, public contact) see a handful
  of requests per minute. `ponytail: fixed window in Postgres; move to Redis
  sliding window if the public endpoint takes real traffic.`
- **Email** → FastAPI background task, sent after commit. There is no persistent
  outbox; a lost transactional email is currently recoverable by a human.
- **Scheduled work** → designed out where possible. `OVERDUE` invoices and
  project `progress` are derived on read rather than written by a nightly job.
  The remaining candidates — due-date reminder notifications — are Phase 2+ and
  can start as a cron-invoked management command against the API host.
- **Caching** → none. Every page is a handful of indexed queries against a
  database with thousands of rows.

## Rationale

Each of these is a service to run, monitor, back up, secure and reason about
during an incident. The load that would justify them does not exist and will not
exist for years at this company's size. Adding them "because production systems
have them" is cargo cult.

## Triggers to revisit

Written down so the decision is re-evaluated on evidence, not on vibes:

- p95 dashboard latency above 500 ms with correct indexes → consider caching.
- Contact-form spam that survives honeypot + Postgres limits → Redis limiter or
  Turnstile.
- Any email whose loss costs money (invoice delivery, Phase 5) → persistent
  outbox with retries.
- Any job that must run reliably off the request path → a real worker.

## Consequences

- The production stack is: web, api, database, storage. Four things.
- The rate limiter's fixed window allows a burst at a window edge — accepted for
  these endpoints, and noted so a reviewer does not report it as a surprise.
