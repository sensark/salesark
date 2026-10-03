"""Add order advance terms and order-linked invoice lines."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0014_order_advance_invoice"
down_revision: Union[str, None] = "0013_ml_predictions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    order_columns = {column["name"] for column in inspector.get_columns("orders")}
    if "advance_payment_pct" not in order_columns:
        op.add_column(
            "orders",
            sa.Column("advance_payment_pct", sa.Numeric(5, 2), nullable=False,
                      server_default="0"),
        )
    invoice_columns = {column["name"]: column for column in inspector.get_columns("invoice_items")}
    invoice_indexes = {index["name"] for index in inspector.get_indexes("invoice_items")}
    foreign_keys = inspector.get_foreign_keys("invoice_items")
    has_order_fk = any("order_item_id" in fk["constrained_columns"] for fk in foreign_keys)
    needs_rebuild = (
        not invoice_columns["delivery_item_id"]["nullable"]
        or "order_item_id" not in invoice_columns
        or not has_order_fk
        or "ix_invoice_items_order_item_id" not in invoice_indexes
    )
    if needs_rebuild:
        with op.batch_alter_table("invoice_items") as batch_op:
            if not invoice_columns["delivery_item_id"]["nullable"]:
                batch_op.alter_column(
                    "delivery_item_id", existing_type=sa.Integer(), nullable=True
                )
            if "order_item_id" not in invoice_columns:
                batch_op.add_column(sa.Column("order_item_id", sa.Integer(), nullable=True))
            if not has_order_fk:
                batch_op.create_foreign_key(
                    "fk_invoice_items_order_item_id_order_items",
                    "order_items", ["order_item_id"], ["id"],
                )
            if "ix_invoice_items_order_item_id" not in invoice_indexes:
                batch_op.create_index("ix_invoice_items_order_item_id", ["order_item_id"])


def downgrade() -> None:
    bind = op.get_bind()
    invoice_columns = {column["name"]: column for column in inspect(bind).get_columns("invoice_items")}
    if "order_item_id" in invoice_columns:
        with op.batch_alter_table("invoice_items") as batch_op:
            batch_op.drop_index("ix_invoice_items_order_item_id")
            batch_op.drop_constraint(
                "fk_invoice_items_order_item_id_order_items", type_="foreignkey"
            )
            batch_op.drop_column("order_item_id")
            batch_op.alter_column(
                "delivery_item_id", existing_type=sa.Integer(), nullable=False
            )
    if "advance_payment_pct" in {
        column["name"] for column in inspect(bind).get_columns("orders")
    }:
        op.drop_column("orders", "advance_payment_pct")