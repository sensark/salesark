"""Add order credit-review flag, legacy address rows, and append-only audit triggers."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0007_audit_credit"
down_revision: Union[str, None] = "0006_quote_rejection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in inspect(connection).get_columns("orders")}
    if "credit_limit_exceeded" not in columns:
        op.add_column(
            "orders",
            sa.Column("credit_limit_exceeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    connection.execute(sa.text(
        "INSERT INTO customer_addresses "
        "(customer_id, label, address_type, line1, city, state, postal_code, country, "
        "is_default_billing, is_default_shipping, active) "
        "SELECT c.id, 'Migrated primary', 'BILLING', COALESCE(NULLIF(c.address, ''), c.name), "
        "COALESCE(NULLIF(c.city, ''), 'Unknown'), COALESCE(NULLIF(c.state, ''), c.region), '', "
        "COALESCE(c.country_code, 'IN'), 1, 0, 1 FROM customers c "
        "WHERE NOT EXISTS (SELECT 1 FROM customer_addresses a WHERE a.customer_id = c.id)"
    ))
    connection.execute(sa.text(
        "INSERT INTO customer_addresses "
        "(customer_id, label, address_type, line1, city, state, postal_code, country, "
        "is_default_billing, is_default_shipping, active) "
        "SELECT c.id, 'Migrated shipping', 'SHIPPING', COALESCE(NULLIF(c.address, ''), c.name), "
        "COALESCE(NULLIF(c.city, ''), 'Unknown'), COALESCE(NULLIF(c.state, ''), c.region), '', "
        "COALESCE(c.country_code, 'IN'), 0, 1, 1 FROM customers c "
        "WHERE NOT EXISTS (SELECT 1 FROM customer_addresses a "
        "WHERE a.customer_id = c.id AND a.is_default_shipping = 1)"
    ))
    dialect = connection.dialect.name
    if dialect == "sqlite":
        connection.execute(sa.text(
            "CREATE TRIGGER IF NOT EXISTS trg_sales_audit_no_update "
            "BEFORE UPDATE ON sales_audit_logs BEGIN "
            "SELECT RAISE(ABORT, 'sales audit log is append-only'); END"
        ))
        connection.execute(sa.text(
            "CREATE TRIGGER IF NOT EXISTS trg_sales_audit_no_delete "
            "BEFORE DELETE ON sales_audit_logs BEGIN "
            "SELECT RAISE(ABORT, 'sales audit log is append-only'); END"
        ))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DROP TRIGGER IF EXISTS trg_sales_audit_no_update"))
    connection.execute(sa.text("DROP TRIGGER IF EXISTS trg_sales_audit_no_delete"))
    op.drop_column("orders", "credit_limit_exceeded")