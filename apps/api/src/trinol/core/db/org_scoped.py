from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class OrgScoped:
    """Mixin for every organization-owned table (DATABASE.md §5).

    Only marks which tables the `do_orm_execute` guard in org_session.py
    applies to and carries the plain FK to the tenant root. Composite FKs to
    *other* org-scoped tables (DATABASE.md §5.1) are declared per-model in
    `__table_args__`, since the target columns differ every time.
    """

    @declared_attr
    def organization_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
