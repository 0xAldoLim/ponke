"""Record reported action and currency on decision outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("decision_outcomes", sa.Column("result_currency", sa.String(3), nullable=True))
    op.add_column("decision_outcomes", sa.Column("user_action", sa.String(250), nullable=True))


def downgrade():
    op.drop_column("decision_outcomes", "user_action")
    op.drop_column("decision_outcomes", "result_currency")
