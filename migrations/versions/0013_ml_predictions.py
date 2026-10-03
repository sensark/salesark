"""Add machine-learning model runs and prediction score tables."""

from typing import Sequence, Union

from alembic import op

from erp.models import ML_TABLES

revision: str = "0013_ml_predictions"
down_revision: Union[str, None] = "0012_invoice_debits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for model in ML_TABLES:
        model.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for model in reversed(ML_TABLES):
        model.__table__.drop(bind=op.get_bind(), checkfirst=True)
