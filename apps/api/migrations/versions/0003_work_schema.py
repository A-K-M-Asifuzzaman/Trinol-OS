"""work module schema: projects, project_members, milestones, tasks,
task_comments, task_checklist_items (Phase 2)

Revision ID: 0003_work_schema
Revises: 0002_csrf_token_plaintext
Create Date: 2026-09-07

Hand-written, same reason as 0001 (DATABASE.md §5.1 composite FKs, native
enums) but checked against modules/work/models.py so `alembic check` agrees.

`task_attachments` is deliberately not created here — it FKs to
`file_objects`, which doesn't exist until Stage 6 (ROADMAP.md Phase 2
checklist). `trinol_app` needs no explicit grant on these new tables: 0001's
`ALTER DEFAULT PRIVILEGES` already covers anything `trinol_migrator` creates
afterward.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_work_schema"
down_revision: str | None = "0002_csrf_token_plaintext"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE project_status AS ENUM "
        "('PLANNING', 'ACTIVE', 'ON_HOLD', 'COMPLETED', 'CANCELLED')"
    )
    op.execute("CREATE TYPE project_health AS ENUM ('ON_TRACK', 'AT_RISK', 'DELAYED')")
    op.execute("CREATE TYPE role_on_project AS ENUM ('LEAD', 'CONTRIBUTOR')")
    op.execute(
        "CREATE TYPE task_status AS ENUM ('TODO', 'IN_PROGRESS', 'REVIEW', 'DONE', 'CANCELLED')"
    )
    op.execute("CREATE TYPE task_priority AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'URGENT')")

    op.execute(
        """
        CREATE TABLE projects (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            project_code text NOT NULL,
            name text NOT NULL,
            description text,
            status project_status NOT NULL DEFAULT 'PLANNING',
            health project_health NOT NULL DEFAULT 'ON_TRACK',
            owner_id uuid NOT NULL,
            start_date date,
            deadline date,
            budget numeric(14, 2),
            currency text NOT NULL DEFAULT 'USD',
            repository_url text,
            production_url text,
            staging_url text,
            archived_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_project_org_code UNIQUE (organization_id, project_code),
            -- Required by composite FKs from milestones, tasks,
            -- project_members, task_comments, task_checklist_items
            -- (DATABASE.md §5.1). Redundant for uniqueness alone; do not
            -- remove as dead weight.
            CONSTRAINT uq_projects_org_id UNIQUE (organization_id, id),
            CONSTRAINT fk_projects_org_owner_memberships FOREIGN KEY (organization_id, owner_id)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT ck_project_dates CHECK (
                deadline IS NULL OR start_date IS NULL OR deadline >= start_date
            )
        )
        """
    )
    op.execute(
        "CREATE TRIGGER trg_projects_updated_at BEFORE UPDATE ON projects "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.execute(
        """
        CREATE TABLE milestones (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            project_id uuid NOT NULL,
            name text NOT NULL,
            description text,
            due_date date,
            completed_at timestamptz,
            position integer NOT NULL DEFAULT 0,
            -- Required by tasks.milestone_id's composite FK (DATABASE.md §5.1).
            CONSTRAINT uq_milestones_org_id UNIQUE (organization_id, id),
            CONSTRAINT fk_milestones_org_project_projects FOREIGN KEY (organization_id, project_id)
                REFERENCES projects (organization_id, id) ON DELETE RESTRICT
        )
        """
    )
    # No separate organization_id index: uq_milestones_org_id already starts
    # with organization_id, same reasoning as memberships (DATABASE.md §1).

    op.execute(
        """
        CREATE TABLE project_members (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            project_id uuid NOT NULL,
            user_id uuid NOT NULL,
            role_on_project role_on_project NOT NULL DEFAULT 'CONTRIBUTOR',
            added_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_project_members_project_user UNIQUE (project_id, user_id),
            CONSTRAINT fk_project_members_org_project_projects
                FOREIGN KEY (organization_id, project_id)
                REFERENCES projects (organization_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_project_members_org_user_memberships
                FOREIGN KEY (organization_id, user_id)
                REFERENCES memberships (organization_id, user_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_project_members_organization_id ON project_members (organization_id)"
    )

    op.execute(
        """
        CREATE TABLE tasks (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            project_id uuid,
            title text NOT NULL,
            description text,
            status task_status NOT NULL DEFAULT 'TODO',
            priority task_priority NOT NULL DEFAULT 'MEDIUM',
            assignee_id uuid,
            created_by uuid NOT NULL,
            milestone_id uuid,
            due_date date,
            start_date date,
            estimated_hours numeric(6, 2),
            actual_hours numeric(6, 2),
            tags text[],
            board_position numeric NOT NULL DEFAULT 0,
            completed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            -- Required by task_comments/task_checklist_items/task_attachments'
            -- composite FKs (DATABASE.md §5.1).
            CONSTRAINT uq_tasks_org_id UNIQUE (organization_id, id),
            CONSTRAINT fk_tasks_org_project_projects FOREIGN KEY (organization_id, project_id)
                REFERENCES projects (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_tasks_org_milestone_milestones FOREIGN KEY (organization_id, milestone_id)
                REFERENCES milestones (organization_id, id) ON DELETE SET NULL,
            CONSTRAINT fk_tasks_org_assignee_memberships FOREIGN KEY (organization_id, assignee_id)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT fk_tasks_org_created_by_memberships FOREIGN KEY (organization_id, created_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT ck_task_completed CHECK (status <> 'DONE' OR completed_at IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX ix_tasks_org_status_due ON tasks (organization_id, status, due_date)")
    op.execute(
        "CREATE INDEX ix_tasks_org_assignee_status ON tasks (organization_id, assignee_id, status)"
    )
    op.execute("CREATE INDEX ix_tasks_project ON tasks (project_id)")
    op.execute(
        "CREATE TRIGGER trg_tasks_updated_at BEFORE UPDATE ON tasks "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.execute(
        """
        CREATE TABLE task_comments (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            task_id uuid NOT NULL,
            author_id uuid NOT NULL,
            body text NOT NULL,
            edited_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_task_comments_org_task_tasks
                FOREIGN KEY (organization_id, task_id)
                REFERENCES tasks (organization_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_task_comments_org_author_memberships
                FOREIGN KEY (organization_id, author_id)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute("CREATE INDEX ix_task_comments_task ON task_comments (task_id)")
    op.execute(
        "CREATE TRIGGER trg_task_comments_updated_at BEFORE UPDATE ON task_comments "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.execute(
        """
        CREATE TABLE task_checklist_items (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            task_id uuid NOT NULL,
            label text NOT NULL,
            done boolean NOT NULL DEFAULT false,
            position integer NOT NULL DEFAULT 0,
            CONSTRAINT fk_task_checklist_items_org_task_tasks FOREIGN KEY (organization_id, task_id)
                REFERENCES tasks (organization_id, id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ix_task_checklist_items_task ON task_checklist_items (task_id)")


def downgrade() -> None:
    op.execute("DROP TABLE task_checklist_items")
    op.execute("DROP TABLE task_comments")
    op.execute("DROP TABLE tasks")
    op.execute("DROP TABLE project_members")
    op.execute("DROP TABLE milestones")
    op.execute("DROP TABLE projects")

    op.execute("DROP TYPE task_priority")
    op.execute("DROP TYPE task_status")
    op.execute("DROP TYPE role_on_project")
    op.execute("DROP TYPE project_health")
    op.execute("DROP TYPE project_status")
