"""Track debit notes applied to an invoice."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0012_invoice_debits"
down_revision: Union[str, None] = "0011_order_cancel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("sales_invoices")}
    if "debit_total" not in columns:
        op.add_column(
            "sales_invoices",
            sa.Column("debit_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("sales_invoices", "debit_total")