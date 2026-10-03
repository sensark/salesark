"""Persist quotation rejection reasons."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0006_quote_rejection"
down_revision: Union[str, None] = "0005_invoice_credits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("quotations")}
    if "rejection_reason" not in columns:
        op.add_column("quotations", sa.Column("rejection_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("quotations", "rejection_reason")