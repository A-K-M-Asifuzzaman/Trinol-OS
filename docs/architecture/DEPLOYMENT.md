# Trinol OS — Deployment

Decision record: [ADR-0009](../adr/0009-deployment-single-host-compose.md).

## 1. Environments

| Environment | Where | Data |
|---|---|---|
| local | docker compose | seeded, disposable |
| staging | one small VM, same compose file | seeded, disposable |
| production | one VM + managed Postgres | real, backed up |

Staging exists so migrations are rehearsed against a production-shaped stack
before they touch real data. It is not optional once Phase 5 stores money.

## 2. Topology

```
Caddy (TLS, HTTP/2, security headers)
 ├── /api/*  → api      (uvicorn, FastAPI)
 └── /*      → web      (next start)
                 └── postgres (managed in prod; container in dev/staging)
                 └── object storage (S3-compatible; MinIO locally)
```

One host. Not Kubernetes, not a service mesh, not autoscaling — this is a
company of a handful of people, and a single VM with a managed database will
carry it comfortably past the point where the answer is obvious. Caddy is
chosen over nginx for automatic certificates, which removes an entire class of
"the site went down because a cert expired" incidents.

## 3. Images

- `apps/api`: multi-stage build on `python:3.12-slim`, dependencies installed
  into a virtualenv in the build stage and copied into a runtime stage. Runs as
  a non-root user. `uvicorn` with `--workers` set from CPU count.
- `apps/web`: multi-stage build, Next.js `output: "standalone"`, non-root user.
- Both images are tagged with the commit SHA. `latest` is not deployed.
- No secrets baked into images; everything comes from the environment at run
  time. `NEXT_PUBLIC_*` variables are build-time and must contain nothing secret.

## 4. Migrations

Migrations run as a **separate one-shot step before the new API starts**, never
from application startup — two concurrently starting containers running Alembic
against one database is how a schema gets corrupted.

```
build → push → migrate (one-shot) → restart api → restart web → smoke check
```

Rollout is: migrate forward, then deploy. Which means every migration in a
release must be compatible with the *previous* code version — additive columns
are nullable or defaulted, renames happen over two releases (add, backfill,
switch, drop). This is a rule, not a nice-to-have, and it is checked at review.

## 5. Configuration

Pydantic `BaseSettings`, validated at startup: the process refuses to boot with
a missing or malformed required variable, rather than failing at the first
request. `.env.example` lists every variable with a dummy value and a comment.

Production secrets are injected by the host's secret mechanism. They are never
in the repository, never in the image, never in CI logs.

## 6. CI/CD

GitHub Actions.

- **PR**: the gate list in [TESTING.md §6](TESTING.md#6-ci-gates).
- **main**: gates, then build and push both images.
- **Deploy**: manual approval, then the §4 sequence over SSH. Manual on purpose
  — a two-person company does not need continuous deployment, and the approval
  step is a cheap place to notice a bad release.
- Rollback: redeploy the previous SHA. A migration that cannot be rolled back
  forward-fixes instead; this is why destructive schema changes are split across
  releases.

## 7. Backups and recovery

- Managed Postgres with daily automated backups and point-in-time recovery.
- Phase 8 Stage 3 (ADR-0014) adds the `pgvector` extension. Dev/CI use the
  `pgvector/pgvector:pg16` image (a drop-in `postgres:16` with pgvector
  built in); production's managed Postgres must have the `vector`
  extension available and enabled by an admin before that migration runs
  — it is not a "trusted" extension, so the ordinary migration role
  cannot install it itself (`infrastructure/postgres/init.sql` handles
  this for dev/CI, where provisioning already runs as a superuser).
- A restore into a scratch database is exercised **before** Phase 5 ships, and
  once per quarter after. An untested backup is not a backup.
- Object storage versioning enabled; attachments are not covered by the database
  backup.

## 8. Health and monitoring

`/health` (process) and `/ready` (database reachable, Alembic at head) — the
container orchestrator uses `/ready` so traffic is not sent to an instance
running against an un-migrated schema. Uptime check on `/health` from outside
the host. Structured logs shipped off-host; error tracking (Sentry or
equivalent) added in Phase 1 because a silent production error is worse than
the dependency.
