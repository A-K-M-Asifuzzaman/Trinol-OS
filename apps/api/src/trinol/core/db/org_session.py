from __future__ import annotations

import uuid
from typing import Any, TypeVar, cast

from sqlalchemy import Select, event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.orm.session import ORMExecuteState
from sqlalchemy.sql.dml import Delete, Update

from trinol.core.db.org_scoped import OrgScoped

_UNSCOPED_OPTION = "trinol_unscoped"

ModelT = TypeVar("ModelT", bound=OrgScoped)


class OrgSession:
    """Every service takes this, never a bare `AsyncSession` (DATABASE.md §5).

    `select()` injects the organization_id filter and `add()` stamps it, but
    those are convenience only — the actual enforcement is the
    `do_orm_execute` guard registered by `register_org_scope_guard()`, which
    fires for any select/update/delete against an `OrgScoped` table regardless
    of how it was built, so a raw `session.execute(select(Task))` is caught
    too.
    """

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def select(self, entity: type[ModelT]) -> Select[tuple[ModelT]]:
        return select(entity).where(entity.organization_id == self.organization_id)

    def add(self, instance: OrgScoped) -> None:
        """Stamps organization_id when unset; **rejects** an instance already
        carrying a different one rather than silently keeping it. This is the
        only check on the insert path — `do_orm_execute` (below) does not fire
        for `session.add()`-triggered inserts, those go through the ORM's
        flush/unit-of-work, not a Core statement."""
        current = getattr(instance, "organization_id", None)
        if current is None:
            instance.organization_id = self.organization_id
        elif current != self.organization_id:
            raise ValueError(
                f"Refusing to add a {type(instance).__name__} whose "
                f"organization_id ({current}) does not match this "
                f"OrgSession's organization ({self.organization_id})."
            )
        self.session.add(instance)

    async def execute(self, stmt: Any) -> Any:
        return await self.session.execute(stmt)

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    @staticmethod
    def unscoped(stmt: Select[Any]) -> Select[Any]:
        """Deliberate, greppable escape hatch for a genuine cross-org read.

        Not used anywhere in Phase 1 — exists so a future admin-tooling query
        has one explicit, auditable spelling instead of reaching for the raw
        session to dodge the guard.
        """
        return stmt.execution_options(**{_UNSCOPED_OPTION: True})


_guard_registered = False


def register_org_scope_guard() -> None:
    """DATABASE.md §5 item 3: on in every environment, not just tests.

    Covers select/update/delete — every Core statement `do_orm_execute` fires
    for. It does *not* cover a bulk Core `insert()` statement (rare; the
    write path here is `OrgSession.add()`, which rejects a mismatched
    organization_id itself, above) or a row loaded then mutated then flushed
    (flush doesn't go through `do_orm_execute` either, but a loaded row was
    necessarily fetched through an already-guarded select).
    `ponytail: select/update/delete guard; extend to bulk insert() if one is
    ever written instead of session.add().`

    Called from both `main.py` (real runtime) and `conftest.py` (tests import
    models/db helpers directly, without necessarily importing `trinol.main`
    first) — idempotent so a process that does both doesn't double-register.
    """
    global _guard_registered
    if _guard_registered:
        return
    _guard_registered = True

    @event.listens_for(SyncSession, "do_orm_execute")
    def _guard(orm_execute_state: ORMExecuteState) -> None:
        if not (
            orm_execute_state.is_select
            or orm_execute_state.is_update
            or orm_execute_state.is_delete
        ):
            return
        if orm_execute_state.execution_options.get(_UNSCOPED_OPTION):
            return

        mapper = orm_execute_state.bind_mapper
        if mapper is None or not issubclass(mapper.class_, OrgScoped):
            return

        # Select, Update and Delete all expose whereclause; is_select/update/
        # delete above guarantees one of those three at runtime, but the
        # common Executable type these share statically doesn't.
        statement = cast("Select[Any] | Update | Delete", orm_execute_state.statement)
        where_clause = statement.whereclause
        if where_clause is None or "organization_id" not in str(where_clause):
            raise RuntimeError(
                "Query against an OrgScoped table has no organization_id "
                "predicate (DATABASE.md §5). Use OrgSession.select(), or "
                "OrgSession.unscoped(stmt) for a deliberate cross-org read."
            )
