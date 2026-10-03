"""Add required approver role to sales orders."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0008_order_approver"
down_revision: Union[str, None] = "0007_audit_credit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("orders")}
    if "required_approver_role" not in columns:
        op.add_column(
            "orders",
            sa.Column("required_approver_role", sa.String(30), nullable=False,
                      server_default="sales_manager"),
        )


def downgrade() -> None:
    op.drop_column("orders", "required_approver_role")