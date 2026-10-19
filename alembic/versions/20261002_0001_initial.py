"""initial projectflow schema

Revision ID: 20261002_0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261002_0001"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table("permissions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.String(255)),
    )
    op.create_table("roles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_table("role_permissions",
        sa.Column("role_id", UUID, sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", UUID, sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table("users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("global_role_id", UUID, sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
        sa.Column("locale", sa.String(10), nullable=False, server_default="es-MX"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table("user_sessions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("family_id", UUID, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by", UUID),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("ip", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

    # Se rompe el ciclo projects <-> workflows creando primero project.default_workflow_id sin FK.
    op.create_table("projects",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("key", sa.String(10), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("lead_user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("issue_counter", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("default_workflow_id", UUID),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    op.create_table("workflows",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(120), nullable=False),
    )
    op.create_foreign_key("fk_projects_default_workflow", "projects", "workflows", ["default_workflow_id"], ["id"])
    op.create_table("project_members",
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", UUID, sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table("issue_types",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(40)),
        sa.Column("is_epic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_subtask", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("project_id", "code", name="uq_issue_type_scope_code"),
    )
    op.create_table("priorities",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(20), nullable=False),
        sa.UniqueConstraint("project_id", "code", name="uq_priority_scope_code"),
    )
    op.create_table("workflow_statuses",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workflow_id", UUID, sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(20), nullable=False),
        sa.Column("is_initial", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("workflow_id", "code", name="uq_workflow_status_code"),
    )
    op.create_table("workflow_transitions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workflow_id", UUID, sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status_id", UUID, sa.ForeignKey("workflow_statuses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_status_id", UUID, sa.ForeignKey("workflow_statuses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("required_permission", sa.String(100)),
        sa.Column("required_fields", postgresql.ARRAY(sa.String())),
        sa.UniqueConstraint("workflow_id", "from_status_id", "to_status_id", name="uq_workflow_transition"),
    )
    op.create_table("issues",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("issue_key", sa.String(40), nullable=False),
        sa.Column("type_id", UUID, sa.ForeignKey("issue_types.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status_id", UUID, sa.ForeignKey("workflow_statuses.id"), nullable=False),
        sa.Column("priority_id", UUID, sa.ForeignKey("priorities.id"), nullable=False),
        sa.Column("reporter_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("creator_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assignee_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("reviewer_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("team_id", UUID),
        sa.Column("epic_id", UUID, sa.ForeignKey("issues.id")),
        sa.Column("parent_issue_id", UUID, sa.ForeignKey("issues.id")),
        sa.Column("sprint_id", UUID),
        sa.Column("rank", sa.String(12, collation="C"), nullable=False),
        sa.Column("story_points", sa.SmallInteger()),
        sa.Column("due_date", sa.Date()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_id", "issue_number", name="uq_project_issue_number"),
        sa.UniqueConstraint("issue_key", name="uq_issue_key"),
        sa.CheckConstraint("story_points IS NULL OR story_points >= 0", name="ck_story_points_nonnegative"),
        sa.CheckConstraint("parent_issue_id IS NULL OR parent_issue_id <> id", name="ck_parent_not_self"),
        sa.CheckConstraint("epic_id IS NULL OR epic_id <> id", name="ck_epic_not_self"),
    )
    op.create_index("ix_issues_project_status", "issues", ["project_id", "status_id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_issues_project_assignee", "issues", ["project_id", "assignee_id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_issues_project_rank", "issues", ["project_id", "rank"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_table("issue_blocks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("issue_id", UUID, sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("blocked_by_user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("unblocked_by_user_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("unblocked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_issue_blocks_issue_id", "issue_blocks", ["issue_id"])
    op.create_index("uq_issue_open_block", "issue_blocks", ["issue_id"], unique=True, postgresql_where=sa.text("unblocked_at IS NULL"))
    op.create_table("comments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("issue_id", UUID, sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_comments_issue_created", "comments", ["issue_id", "created_at"])
    op.create_table("audit_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", UUID, nullable=False),
        sa.Column("project_id", UUID),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("actor_user_id", UUID, nullable=False),
        sa.Column("field_name", sa.String(100)),
        sa.Column("old_value", sa.Text()),
        sa.Column("new_value", sa.Text()),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("request_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_entity", "audit_events", ["entity_type", "entity_id", "created_at"])
    op.create_index("ix_audit_project", "audit_events", ["project_id", "created_at"])
    op.create_table("outbox_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", UUID, nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(1000)),
    )
    op.create_index("ix_outbox_pending", "outbox_events", ["created_at"], postgresql_where=sa.text("processed_at IS NULL"))
    op.create_table("notifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("recipient_user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", UUID, nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("recipient_user_id", "event_id", name="uq_notification_event_recipient"),
    )
    op.create_index("ix_notifications_unread", "notifications", ["recipient_user_id", "created_at"], postgresql_where=sa.text("read_at IS NULL"))


def downgrade() -> None:
    for table in [
        "notifications", "outbox_events", "audit_events", "comments", "issue_blocks", "issues",
        "workflow_transitions", "workflow_statuses", "priorities", "issue_types", "project_members"
    ]:
        op.drop_table(table)
    op.drop_constraint("fk_projects_default_workflow", "projects", type_="foreignkey")
    op.drop_table("workflows")
    op.drop_table("projects")
    op.drop_table("user_sessions")
    op.drop_table("users")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("permissions")
