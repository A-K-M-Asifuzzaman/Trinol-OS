"""meetings module schema: meetings, meeting_participants,
meeting_decisions, meeting_actions (Phase 4)

Revision ID: 0006_meetings_schema
Revises: 0005_crm_schema
Create Date: 2026-09-10

Hand-written, same reason as 0001/0003/0004/0005 (DATABASE.md §5.1
composite FKs, native enums) but checked against modules/meetings/models.py
so `alembic check` agrees.

`meetings` must be created before its three sub-resource tables (their
composite FKs reference `meetings`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_meetings_schema"
down_revision: str | None = "0005_crm_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE meeting_participant_response AS ENUM "
        "('PENDING', 'ACCEPTED', 'DECLINED', 'TENTATIVE')"
    )

    op.execute(
        """
        CREATE TABLE meetings (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            title text NOT NULL,
            description text,
            starts_at timestamptz NOT NULL,
            ends_at timestamptz NOT NULL,
            client_id uuid,
            project_id uuid,
            meeting_url text,
            location text,
            notes text,
            external_event_id text,
            created_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            -- Required by composite FKs from meeting_participants,
            -- meeting_decisions, meeting_actions, and a future
            -- document_references.meeting_id (DATABASE.md §5.1). Redundant
            -- for uniqueness alone; do not remove as dead weight.
            CONSTRAINT uq_meetings_org_id UNIQUE (organization_id, id),
            CONSTRAINT fk_meetings_org_client_clients FOREIGN KEY (organization_id, client_id)
                REFERENCES clients (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_meetings_org_project_projects FOREIGN KEY (organization_id, project_id)
                REFERENCES projects (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_meetings_org_created_by_memberships
                FOREIGN KEY (organization_id, created_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT ck_meeting_times CHECK (ends_at > starts_at)
        )
        """
    )
    op.execute("CREATE INDEX ix_meetings_org_starts_at ON meetings (organization_id, starts_at)")
    op.execute("CREATE INDEX ix_meetings_org_client ON meetings (organization_id, client_id)")
    op.execute("CREATE INDEX ix_meetings_org_project ON meetings (organization_id, project_id)")
    op.execute("CREATE INDEX ix_meetings_org_created_by ON meetings (organization_id, created_by)")
    op.execute(
        "CREATE TRIGGER trg_meetings_updated_at BEFORE UPDATE ON meetings "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.execute(
        """
        CREATE TABLE meeting_participants (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            meeting_id uuid NOT NULL,
            user_id uuid,
            external_email text,
            response meeting_participant_response NOT NULL DEFAULT 'PENDING',
            CONSTRAINT fk_meeting_participants_org_meeting_meetings
                FOREIGN KEY (organization_id, meeting_id)
                REFERENCES meetings (organization_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_meeting_participants_org_user_memberships
                FOREIGN KEY (organization_id, user_id)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT ck_meeting_participant_identity
                CHECK ((user_id IS NOT NULL) <> (external_email IS NOT NULL))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_meeting_participants_org_meeting "
        "ON meeting_participants (organization_id, meeting_id)"
    )
    op.execute(
        "CREATE INDEX ix_meeting_participants_org_user "
        "ON meeting_participants (organization_id, user_id)"
    )

    op.execute(
        """
        CREATE TABLE meeting_decisions (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            meeting_id uuid NOT NULL,
            body text NOT NULL,
            decided_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_meeting_decisions_org_meeting_meetings
                FOREIGN KEY (organization_id, meeting_id)
                REFERENCES meetings (organization_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_meeting_decisions_org_decided_by_memberships
                FOREIGN KEY (organization_id, decided_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_meeting_decisions_org_meeting "
        "ON meeting_decisions (organization_id, meeting_id)"
    )
    op.execute(
        "CREATE INDEX ix_meeting_decisions_org_decided_by "
        "ON meeting_decisions (organization_id, decided_by)"
    )

    op.execute(
        """
        CREATE TABLE meeting_actions (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            meeting_id uuid NOT NULL,
            description text NOT NULL,
            owner_id uuid,
            due_date date,
            task_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_meeting_actions_org_meeting_meetings
                FOREIGN KEY (organization_id, meeting_id)
                REFERENCES meetings (organization_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_meeting_actions_org_owner_memberships
                FOREIGN KEY (organization_id, owner_id)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT fk_meeting_actions_org_task_tasks FOREIGN KEY (organization_id, task_id)
                REFERENCES tasks (organization_id, id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_meeting_actions_org_meeting "
        "ON meeting_actions (organization_id, meeting_id)"
    )
    op.execute(
        "CREATE INDEX ix_meeting_actions_org_owner ON meeting_actions (organization_id, owner_id)"
    )
    op.execute(
        "CREATE INDEX ix_meeting_actions_org_task ON meeting_actions (organization_id, task_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE meeting_actions")
    op.execute("DROP TABLE meeting_decisions")
    op.execute("DROP TABLE meeting_participants")
    op.execute("DROP TABLE meetings")
    op.execute("DROP TYPE meeting_participant_response")
