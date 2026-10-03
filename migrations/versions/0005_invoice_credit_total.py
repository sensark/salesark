"""Track credit notes applied to an invoice."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0005_invoice_credits"
down_revision: Union[str, None] = "0004_customer_country"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("sales_invoices")}
    if "credit_total" not in columns:
        op.add_column(
            "sales_invoices",
            sa.Column("credit_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("sales_invoices", "credit_total")