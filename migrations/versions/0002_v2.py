"""Add market cache, tasks, statement previews and spreadsheet outbox."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def owned():
    return [
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table(
        "market_cache",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("cache_key", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "cache_key"),
    )
    op.create_index("ix_market_cache_expires_at", "market_cache", ["expires_at"])
    op.create_table(
        "projects",
        *owned(),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("user_id", "name"),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])
    op.create_table(
        "tasks",
        *owned(),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id")),
        sa.Column("estimated_minutes", sa.Integer()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tasks_due_at", "tasks", ["due_at"])
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_table(
        "statement_imports",
        *owned(),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(250), nullable=False),
        sa.Column("account_id", sa.String(32), sa.ForeignKey("accounts.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_statement_imports_file_hash", "statement_imports", ["file_hash"])
    op.create_index("ix_statement_imports_user_id", "statement_imports", ["user_id"])
    op.create_table(
        "spreadsheet_sync_outbox",
        *owned(),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.UniqueConstraint("user_id", "entity_type", "entity_id", "operation"),
    )
    op.create_index("ix_spreadsheet_sync_outbox_user_id", "spreadsheet_sync_outbox", ["user_id"])


def downgrade():
    op.drop_index("ix_spreadsheet_sync_outbox_user_id", table_name="spreadsheet_sync_outbox")
    op.drop_table("spreadsheet_sync_outbox")
    op.drop_index("ix_statement_imports_user_id", table_name="statement_imports")
    op.drop_index("ix_statement_imports_file_hash", table_name="statement_imports")
    op.drop_table("statement_imports")
    op.drop_index("ix_tasks_user_id", table_name="tasks")
    op.drop_index("ix_tasks_due_at", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_market_cache_expires_at", table_name="market_cache")
    op.drop_table("market_cache")
