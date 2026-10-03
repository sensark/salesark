"""Track sales order fulfillment separately from approval status."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0010_fulfillment"
down_revision: Union[str, None] = "0009_accounting_maps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("orders")}
    if "fulfillment_status" not in columns:
        op.add_column(
            "orders",
            sa.Column("fulfillment_status", sa.String(24), nullable=False, server_default="OPEN"),
        )


def downgrade() -> None:
    op.drop_column("orders", "fulfillment_status")