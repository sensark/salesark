"""Add configurable accounting account mappings."""

from typing import Sequence, Union

from alembic import op

from erp.models import AccountingMapping

revision: str = "0009_accounting_maps"
down_revision: Union[str, None] = "0008_order_approver"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    AccountingMapping.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    AccountingMapping.__table__.drop(bind=op.get_bind(), checkfirst=True)