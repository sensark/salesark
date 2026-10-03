from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from erp.models import InventoryMovement, Product, User, Warehouse, WarehouseStock
from erp.permissions import require_action


def default_warehouse(session: Session) -> Warehouse:
    warehouse = session.scalar(select(Warehouse).where(Warehouse.code == "KOLKATA"))
    if warehouse is None:
        warehouse = Warehouse(code="KOLKATA", name="Krypton Main Warehouse", state="West Bengal")
        session.add(warehouse)
        session.flush()
    return warehouse


def record_movement(
    session: Session,
    *,
    product_id: int,
    qty_delta: int,
    source_type: str,
    source_id: int,
    source_line_id: int | None,
    actor_id: int | None,
    warehouse_id: int | None = None,
    reason: str | None = None,
    occurred_at: datetime | None = None,
    update_product_stock: bool = True,
) -> InventoryMovement:
    if qty_delta == 0:
        raise ValueError("Inventory movement quantity cannot be zero.")
    required_action = {
        "ORDER_APPROVAL": "order.approve",
        "ORDER_CANCELLATION": "order.cancel",
        "SALES_RETURN": "return.receive",
        "STOCK_ADJUSTMENT": "inventory.adjust",
    }.get(source_type)
    if required_action:
        actor = session.get(User, actor_id) if actor_id else None
        if actor is None:
            raise ValueError("An authorized user is required for this inventory movement.")
        try:
            require_action(actor.role, required_action)
        except PermissionError as exc:
            raise ValueError(str(exc)) from exc
    if warehouse_id is None:
        warehouse_id = default_warehouse(session).id
    if update_product_stock:
        result = session.execute(
            update(Product)
            .where(
                Product.id == product_id,
                Product.stock + qty_delta >= 0,
            )
            .values(stock=Product.stock + qty_delta)
        ).rowcount
        if result != 1:
            product = session.get(Product, product_id)
            raise ValueError(
                f"Inventory movement would make {product.name if product else product_id} stock negative."
            )
    row = session.scalar(
        select(WarehouseStock).where(
            WarehouseStock.warehouse_id == warehouse_id,
            WarehouseStock.product_id == product_id,
        )
    )
    if row is None:
        current_stock = session.scalar(select(Product.stock).where(Product.id == product_id)) or 0
        row = WarehouseStock(
            warehouse_id=warehouse_id,
            product_id=product_id,
            on_hand=current_stock - qty_delta if update_product_stock else current_stock,
        )
        session.add(row)
        session.flush()
    if row.on_hand + qty_delta < 0:
        raise ValueError("Inventory movement would make warehouse stock negative.")
    row.on_hand += qty_delta
    movement = InventoryMovement(
        product_id=product_id,
        warehouse_id=warehouse_id,
        source_type=source_type,
        source_id=source_id,
        source_line_id=source_line_id,
        qty_delta=qty_delta,
        reason=reason,
        actor_id=actor_id,
        occurred_at=occurred_at or datetime.now(),
    )
    session.add(movement)
    return movement