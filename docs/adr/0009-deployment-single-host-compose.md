# ADR-0009 — Single-host Docker Compose deployment

Status: Accepted (Phase 0)

## Context

The initial and only user is TrinolIT — a handful of people. MASTER_PROMPT §4
asks for Docker and Docker Compose and does not name a hosting target.

## Decision

One VM running Docker Compose behind Caddy, with **managed** PostgreSQL in
production. Images tagged by commit SHA, built in CI, deployed by a manually
approved GitHub Actions job. Migrations run as a one-shot step before the API
restarts.

Caddy over nginx: automatic certificate issuance and renewal removes a whole
category of outage.

Managed Postgres over a container in production: backups, point-in-time
recovery and patching are someone else's job, and this is the data that must not
be lost.

## Alternatives rejected

**Kubernetes.** An order of magnitude more operational surface than this
workload justifies. Revisit if there is ever a real multi-region or
multi-tenant-scale requirement.

**A PaaS (Vercel + Fly/Railway).** Genuinely attractive and lower-effort. Left
open as a decision for the operator rather than assumed, because it splits the
two apps across providers and changes the same-origin cookie assumption in
[AUTH.md](../architecture/AUTH.md). **Flagged for the user in the Phase 0
report.**

**Self-hosted PostgreSQL in a container in production.** Fine until the first
restore, which is the worst time to discover the backup was never tested.

## Consequences

- Deployment is a compose file and a short script; anyone on the team can read it.
- Single host is a single point of failure. Accepted for an internal tool;
  restoring from image + backup is a documented, rehearsed procedure.
- Same-origin serving of web and API is a load-bearing assumption of the auth
  design. Changing hosting shape means revisiting ADR-0002's cookie strategy.
