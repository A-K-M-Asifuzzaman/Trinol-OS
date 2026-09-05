from __future__ import annotations

import pytest
from sqlalchemy import text

from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped
from trinol.modules.identity import models as identity_models  # noqa: F401
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
    result = await db_session.execute(
        text(
            """
            SELECT
                tc.constraint_name,
                tc.table_name AS source_table,
                array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS source_columns,
                ccu.table_name AS target_table,
                array_agg(ccu.column_name ORDER BY kcu.ordinal_position) AS target_columns
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
            GROUP BY tc.constraint_name, tc.table_name, ccu.table_name
            """
        )
    )
    return result.mappings().all()


async def _unique_column_sets(db_session, table_name: str) -> list[set[str]]:
    result = await db_session.execute(
        text(
            """
            SELECT array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS columns
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type IN ('UNIQUE', 'PRIMARY KEY')
                AND tc.table_schema = 'public' AND tc.table_name = :table_name
            GROUP BY tc.constraint_name
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
