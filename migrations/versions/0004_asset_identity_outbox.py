"""Add exchange-aware asset identity and Sheets retry observability."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("exchange", sa.String(30), nullable=True))
    op.add_column("assets", sa.Column("provider_symbol", sa.String(40), nullable=True))
    op.execute("UPDATE assets SET provider_symbol = symbol WHERE provider_symbol IS NULL")
    op.add_column(
        "spreadsheet_sync_outbox", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column("spreadsheet_sync_outbox", "last_attempt_at")
    op.drop_column("assets", "provider_symbol")
    op.drop_column("assets", "exchange")
