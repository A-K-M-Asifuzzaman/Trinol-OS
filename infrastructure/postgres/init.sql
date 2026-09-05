-- Creates the two Postgres roles required by ADR-0006/DATABASE.md: a
-- migrator role that owns objects and runs Alembic, and a runtime role the
-- API actually connects as (denied UPDATE/DELETE on activity_events so the
-- append-only guarantee holds even against a compromised app, not just by
-- convention).
--
-- Run automatically by Docker Compose (docker-entrypoint-initdb.d, after the
-- postgres image has created the trinol_os database). For a local, non-Docker
-- Postgres, `make db-setup` runs this against an already-created database.
-- Idempotent: safe to run against an existing cluster.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trinol_migrator') THEN
        CREATE ROLE trinol_migrator LOGIN PASSWORD 'trinol_migrator';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trinol_app') THEN
        CREATE ROLE trinol_app LOGIN PASSWORD 'trinol_app';
    END IF;
END
$$;

ALTER DATABASE trinol_os OWNER TO trinol_migrator;
GRANT CONNECT ON DATABASE trinol_os TO trinol_app;
