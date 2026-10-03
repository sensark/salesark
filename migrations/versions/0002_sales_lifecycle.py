"""Add Krypton India sales lifecycle tables and legacy-compatible columns."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from erp.models import Base

revision: str = "0002_sales"
down_revision: Union[str, None] = "0001_legacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_COLUMNS = {
    "users": [
        sa.Column("monthly_target", sa.Numeric(12, 2), nullable=False, server_default="0"),
    ],
    "customers": [
        sa.Column("customer_type", sa.String(30), nullable=False, server_default="BUSINESS"),
        sa.Column("customer_status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("contact_person", sa.String(120), nullable=True),
        sa.Column("gstin", sa.String(15), nullable=True),
        sa.Column("pan", sa.String(10), nullable=True),
        sa.Column("gst_registration_type", sa.String(30), nullable=False, server_default="UNREGISTERED"),
        sa.Column("state", sa.String(80), nullable=True),
        sa.Column("place_of_supply_state", sa.String(80), nullable=True),
        sa.Column("credit_limit", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("credit_period_days", sa.Integer(), nullable=False, server_default="0"),
    ],
    "products": [
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("unit", sa.String(20), nullable=False, server_default="EA"),
        sa.Column("hsn_sac", sa.String(20), nullable=True),
        sa.Column("tax_category", sa.String(40), nullable=False, server_default="STANDARD"),
        sa.Column("gst_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("cess_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
    ],
    "orders": [
        sa.Column("taxable_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("cgst_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("sgst_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("igst_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("cess_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("customer_po_number", sa.String(80), nullable=True),
        sa.Column("expected_delivery_date", sa.DateTime(), nullable=True),
        sa.Column("billing_address_snapshot", sa.Text(), nullable=True),
        sa.Column("shipping_address_snapshot", sa.Text(), nullable=True),
        sa.Column("source_quotation_id", sa.Integer(), nullable=True),
    ],
    "order_items": [
        sa.Column("hsn_sac", sa.String(20), nullable=True),
        sa.Column("gst_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("cess_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("taxable_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("cgst_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("sgst_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("igst_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("cess_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
    ],
}


def upgrade() -> None:
    connection = op.get_bind()
    Base.metadata.create_all(connection)
    inspector = inspect(connection)
    for table, columns in LEGACY_COLUMNS.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
                existing.add(column.name)


def downgrade() -> None:
    raise RuntimeError("The sales lifecycle migration is intentionally forward-only; restore the pre-migration backup to roll back.")