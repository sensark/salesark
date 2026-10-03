"""Add sales order cancellation metadata."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0011_order_cancel"
down_revision: Union[str, None] = "0010_fulfillment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("orders")}
    if "cancelled_by_id" not in columns:
        op.add_column("orders", sa.Column("cancelled_by_id", sa.Integer(), nullable=True))
    if "cancelled_at" not in columns:
        op.add_column("orders", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    if "cancellation_reason" not in columns:
        op.add_column("orders", sa.Column("cancellation_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "cancellation_reason")
    op.drop_column("orders", "cancelled_at")
    op.drop_column("orders", "cancelled_by_id")