import sys
from pathlib import Path

from alembic import context
from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from erp.db import engine  # noqa: E402
from erp.models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        restore_sqlite_foreign_keys = False
        if connection.dialect.name == "sqlite":
            columns = {
                column["name"]: column
                for column in inspect(connection).get_columns("invoice_items")
            }
            indexes = {
                index["name"]
                for index in inspect(connection).get_indexes("invoice_items")
            }
            foreign_keys = inspect(connection).get_foreign_keys(
                "invoice_items"
            )
            has_order_fk = any(
                "order_item_id" in fk["constrained_columns"]
                for fk in foreign_keys
            )
            needs_rebuild = (
                not columns["delivery_item_id"]["nullable"]
                or "order_item_id" not in columns
                or not has_order_fk
                or "ix_invoice_items_order_item_id" not in indexes
            )
            restore_sqlite_foreign_keys = (
                needs_rebuild
                and connection.exec_driver_sql(
                    "PRAGMA foreign_keys"
                ).scalar() == 1
            )
            if restore_sqlite_foreign_keys:
                connection.commit()
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        try:
            with context.begin_transaction():
                context.run_migrations()
            if restore_sqlite_foreign_keys:
                violations = connection.exec_driver_sql(
                    "PRAGMA foreign_key_check"
                ).all()
                if violations:
                    raise RuntimeError(
                        "Migration produced foreign-key violations."
                    )
        finally:
            if restore_sqlite_foreign_keys:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()