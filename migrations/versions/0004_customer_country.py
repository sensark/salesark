"""Add country code to customers."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0004_customer_country"
down_revision: Union[str, None] = "0003_customer_prices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("customers")}
    if "country_code" not in columns:
        op.add_column("customers", sa.Column("country_code", sa.String(2), nullable=False, server_default="IN"))


def downgrade() -> None:
    op.drop_column("customers", "country_code")