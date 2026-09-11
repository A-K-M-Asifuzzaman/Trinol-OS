from __future__ import annotations

import pytest
from sqlalchemy import text

from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped

# Imported for their side effect of registering tables on Base.metadata, same
# reasoning as migrations/env.py — _ORG_SCOPED_TABLES below is derived from
# whatever's actually in Base.registry, which only reflects a module if
# something has imported it. Before this fix, `work` and `crm` were never
# imported directly here at all: `work` happened to get registered anyway
# because tests/factories.py (loaded by every test session via conftest.py)
# already imports it for make_project/make_task — a coincidence, not a
# guarantee. `crm` has no such accidental import yet (tests/factories.py
# gains make_client/make_lead in a later Phase 3 stage), so without this fix
# _ORG_SCOPED_TABLES silently excluded clients/leads/lead_stage_events/
# contact_submissions entirely — both composite-FK tests below passed
# vacuously on them, the same *shape* of "checks nothing, reports success"
# bug Stage 6 of Phase 2 already found once for a different reason (that
# time it was a Postgres privilege-visibility issue, not a Python import
# gap). Confirmed empirically: before this fix, a direct check of
# Base.registry.mappers with only identity/platform imported did not
# contain "clients"/"leads" at all.
from trinol.modules.crm import models as crm_models  # noqa: F401
from trinol.modules.documents import models as documents_models  # noqa: F401
from trinol.modules.finance import models as finance_models  # noqa: F401
from trinol.modules.identity import models as identity_models  # noqa: F401
from trinol.modules.meetings import models as meetings_models  # noqa: F401
from trinol.modules.work import models as work_models  # noqa: F401
from trinol.platform import models as platform_models  # noqa: F401

pytestmark = pytest.mark.usefixtures("db_session")

# TESTING.md §4 item 5: every FK between two org-scoped tables must be
# composite (organization_id + the referenced id), and the referenced table
# must carry a matching UNIQUE(organization_id, id) — see DATABASE.md §5.1.
# This walks information_schema against the *migrated* database rather than
# the ORM metadata, so it catches what actually got created, not just what
# the models claim.

_ORG_SCOPED_TABLES = {
    mapper.local_table.name
    for mapper in Base.registry.mappers
    if issubclass(mapper.class_, OrgScoped)
}

# users is global and is the documented exception (DATABASE.md §5.1): person
# columns reference memberships, but activity_events.actor_id and
# invitations.invited_by deliberately reference users directly so history
# survives someone leaving the org.
_ALLOWED_SINGLE_COLUMN_TARGETS = {"users"}


async def _foreign_keys(db_session):
    """Queries `pg_catalog` directly, not `information_schema.
    constraint_column_usage` — that view's own definition (`pg_get_viewdef`)
    filters on `pg_has_role(tblowner, 'USAGE')`, which checks *role
    membership in the table's owner*, not any of the SELECT/INSERT/UPDATE/
    DELETE table-level grants `trinol_app` actually holds. Since
    `trinol_app` is deliberately not a member of `trinol_migrator`
    (ADR-0006 — that's the entire point of the two-role split), this view
    has returned **zero rows** to every test in this file since Stage 3,
    silently making both assertions below vacuously true for the whole
    project's history. Found while adding Stage 6's dedicated
    `organizations.logo_file_id` regression test, which asserts a row
    actually exists rather than merely "no violations found" — a positive
    assertion an empty result set can't satisfy by accident, unlike the
    other two. `pg_constraint`/`pg_attribute`/`pg_class` are ordinary
    catalog tables with no such owner-role restriction, and building each
    column array with an explicit position-preserving subquery (instead of
    joining two one-to-many views and `array_agg`-ing the join's cross
    product) also avoids a second, independent bug: the old query
    duplicated every column across the number of columns on the other
    side (confirmed empirically — a 2-column-source/2-column-target FK
    produced 4 rows before aggregation, not 2)."""
    result = await db_session.execute(
        text(
            """
            SELECT
                con.conname AS constraint_name,
                rel.relname AS source_table,
                (
                    SELECT array_agg(attname ORDER BY array_position(con.conkey, attnum))
                    FROM pg_attribute
                    WHERE attrelid = con.conrelid AND attnum = ANY(con.conkey)
                ) AS source_columns,
                frel.relname AS target_table,
                (
                    SELECT array_agg(attname ORDER BY array_position(con.confkey, attnum))
                    FROM pg_attribute
                    WHERE attrelid = con.confrelid AND attnum = ANY(con.confkey)
                ) AS target_columns
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_class frel ON frel.oid = con.confrelid
            JOIN pg_namespace nsp ON nsp.oid = con.connamespace
            WHERE con.contype = 'f' AND nsp.nspname = 'public'
            """
        )
    )
    return result.mappings().all()


async def _unique_column_sets(db_session, table_name: str) -> list[set[str]]:
    """Same `pg_catalog` fix as `_foreign_keys` above — this one happened
    to still return correct results via `information_schema` (unique/
    primary-key constraints go through `key_column_usage` alone, which
    isn't owner-role-gated the way `constraint_column_usage` is), but is
    rewritten for consistency with the function it feeds."""
    result = await db_session.execute(
        text(
            """
            SELECT
                con.conname AS constraint_name,
                (
                    SELECT array_agg(attname)
                    FROM pg_attribute
                    WHERE attrelid = con.conrelid AND attnum = ANY(con.conkey)
                ) AS columns
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = con.connamespace
            WHERE con.contype IN ('p', 'u') AND nsp.nspname = 'public' AND rel.relname = :table_name
            """
        ),
        {"table_name": table_name},
    )
    return [set(row["columns"]) for row in result.mappings().all()]


async def test_every_fk_between_org_scoped_tables_is_composite(db_session) -> None:
    violations = []
    for fk in await _foreign_keys(db_session):
        if fk["source_table"] not in _ORG_SCOPED_TABLES:
            continue
        if fk["target_table"] in _ALLOWED_SINGLE_COLUMN_TARGETS:
            continue
        if fk["target_table"] not in _ORG_SCOPED_TABLES:
            continue
        if "organization_id" not in fk["source_columns"] or len(fk["source_columns"]) < 2:
            violations.append(
                f"{fk['source_table']}.{fk['source_columns']} -> {fk['target_table']} "
                f"is a single-column FK between org-scoped tables (constraint "
                f"{fk['constraint_name']}); it must be composite on "
                f"(organization_id, ...) per DATABASE.md §5.1"
            )
    assert not violations, "\n".join(violations)


async def test_every_composite_fk_target_has_matching_unique_constraint(db_session) -> None:
    violations = []
    for fk in await _foreign_keys(db_session):
        if len(fk["target_columns"]) < 2:
            continue
        target_unique_sets = await _unique_column_sets(db_session, fk["target_table"])
        if set(fk["target_columns"]) not in target_unique_sets:
            violations.append(
                f"{fk['target_table']}{tuple(fk['target_columns'])} is referenced by a "
                f"composite FK ({fk['constraint_name']}) but has no matching UNIQUE "
                f"constraint on exactly those columns"
            )
    assert not violations, "\n".join(violations)


async def test_organizations_logo_file_id_fk_is_composite(db_session) -> None:
    """Dedicated regression check (ROADMAP.md Stage 6): `organizations` is
    the tenant root, not `OrgScoped` (it has no `organization_id` column),
    so `test_every_fk_between_org_scoped_tables_is_composite` above never
    walks its FKs at all — a regression here (e.g. a future migration
    flattening this into a single-column FK to `file_objects.id`) would go
    undetected by the generic check. `organizations.id` is the tenant key
    for this one FK (DATABASE.md §3), so this is checked by name instead."""
    fks = await _foreign_keys(db_session)
    logo_fk = next(
        (
            fk
            for fk in fks
            if fk["constraint_name"] == "fk_organizations_id_logo_file_id_file_objects"
        ),
        None,
    )
    assert logo_fk is not None, "organizations.logo_file_id's composite FK is missing"
    assert set(logo_fk["source_columns"]) == {"id", "logo_file_id"}
    assert logo_fk["target_table"] == "file_objects"
    assert set(logo_fk["target_columns"]) == {"organization_id", "id"}
