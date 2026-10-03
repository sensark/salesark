"""Associate customers with an optional price list."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0003_customer_prices"
down_revision: Union[str, None] = "0002_sales"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("customers")}
    if "price_list_id" not in columns:
        op.add_column("customers", sa.Column("price_list_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "price_list_id")