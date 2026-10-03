from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from erp.models import (
    Delivery,
    DeliveryItem,
    Order,
    OrderItem,
    SalesInvoice,
    STATUS_APPROVED,
    User,
)
from erp.permissions import require_action
from erp.services import audit
from erp.services.documents import next_document_number
from erp.services.inventory import default_warehouse
from erp.services.discounts import money


class DeliveryError(ValueError):
    pass


def _require_warehouse_action(session: Session, actor_id: int, action: str) -> User:
    actor = session.get(User, actor_id)
    if actor is None:
        raise DeliveryError("User not found.")
    try:
        require_action(actor.role, action)
    except PermissionError as exc:
        raise DeliveryError(str(exc)) from exc
    return actor


def delivered_quantities(session: Session, order_id: int, include_drafts: bool = True) -> dict[int, int]:
    statuses = ["CONFIRMED", "DRAFT"] if include_drafts else ["CONFIRMED"]
    rows = session.execute(
        select(DeliveryItem.order_item_id, func.coalesce(func.sum(DeliveryItem.qty), 0))
        .join(Delivery, Delivery.id == DeliveryItem.delivery_id)
        .where(Delivery.order_id == order_id, Delivery.status.in_(statuses))
        .group_by(DeliveryItem.order_item_id)
    )
    return {item_id: int(qty) for item_id, qty in rows}


def open_order_items(session: Session, order_id: int) -> list[tuple[OrderItem, int]]:
    order = session.get(Order, order_id)
    if order is None or order.status != STATUS_APPROVED or not advance_payment_satisfied(session, order):
        return []
    allocated = delivered_quantities(session, order_id)
    items = session.scalars(select(OrderItem).where(OrderItem.order_id == order_id)).all()
    return [(item, max(0, item.qty - allocated.get(item.id, 0))) for item in items]


def advance_payment_satisfied(session: Session, order: Order) -> bool:
    required = money(order.total * order.advance_payment_pct / 100)
    if required <= 0:
        return True
    invoice = session.scalar(
        select(SalesInvoice).where(
            SalesInvoice.order_id == order.id,
            SalesInvoice.status != "CANCELLED",
        ).order_by(SalesInvoice.invoice_date)
    )
    return bool(invoice and invoice.amount_paid >= required)


def list_ready_orders(session: Session) -> list[Order]:
    orders = session.scalars(
        select(Order).where(Order.status == STATUS_APPROVED).order_by(Order.created_at)
    ).all()
    return [order for order in orders if any(qty for _, qty in open_order_items(session, order.id))]


def list_orders_waiting_for_advance(
    session: Session,
) -> list[tuple[Order, Decimal, Decimal]]:
    orders = session.scalars(
        select(Order)
        .where(Order.status == STATUS_APPROVED, Order.advance_payment_pct > 0)
        .options(selectinload(Order.customer), selectinload(Order.items))
    ).all()
    waiting = []
    for order in orders:
        delivered = delivered_quantities(session, order.id)
        if not any(
            item.qty > delivered.get(item.id, 0) for item in order.items
        ):
            continue
        required = money(order.total * order.advance_payment_pct / 100)
        if advance_payment_satisfied(session, order):
            continue
        invoice = session.scalar(
            select(SalesInvoice).where(
                SalesInvoice.order_id == order.id,
                SalesInvoice.status != "CANCELLED",
            ).order_by(SalesInvoice.invoice_date)
        )
        paid = invoice.amount_paid if invoice else money(0)
        waiting.append((order, required, paid))
    return waiting


def create_delivery(
    session: Session,
    *,
    order_id: int,
    actor_id: int,
    quantities: dict[int, int],
    warehouse_id: int | None = None,
    transport_name: str = "",
    tracking_number: str = "",
    notes: str = "",
) -> Delivery:
    _require_warehouse_action(session, actor_id, "delivery.create")
    order = session.get(Order, order_id)
    if order is None or order.status != STATUS_APPROVED:
        raise DeliveryError("Deliveries can only be created for approved orders.")
    if not advance_payment_satisfied(session, order):
        raise DeliveryError(
            "The required advance payment must be allocated to the order invoice before dispatch."
        )
    if not quantities or any(qty <= 0 for qty in quantities.values()):
        raise DeliveryError("Enter at least one positive delivery quantity.")
    open_items = dict((item.id, remaining) for item, remaining in open_order_items(session, order_id))
    for item_id, qty in quantities.items():
        if item_id not in open_items or qty > open_items[item_id]:
            raise DeliveryError(f"Delivery quantity exceeds the remaining quantity for order line {item_id}.")
    if warehouse_id is None:
        warehouse_id = default_warehouse(session).id

    delivery = Delivery(
        delivery_no=next_document_number(session, "DELIVERY"),
        order_id=order_id,
        warehouse_id=warehouse_id,
        status="DRAFT",
        transport_name=transport_name.strip() or None,
        tracking_number=tracking_number.strip() or None,
        notes=notes.strip() or None,
        created_by_id=actor_id,
        items=[DeliveryItem(order_item_id=item_id, qty=qty) for item_id, qty in quantities.items()],
    )
    session.add(delivery)
    session.flush()
    audit.record(
        session, actor_id=actor_id, action="CREATE", entity_type="DELIVERY",
        entity_id=delivery.id, changes={"status": "DRAFT", "quantities": quantities},
    )
    return delivery


def confirm_delivery(
    session: Session,
    delivery_id: int,
    actor_id: int,
    *,
    receiver_name: str = "",
    confirmed_at: datetime | None = None,
) -> Delivery:
    _require_warehouse_action(session, actor_id, "delivery.confirm")
    delivery = session.get(Delivery, delivery_id)
    if delivery is None or delivery.status != "DRAFT":
        raise DeliveryError("Only draft deliveries can be confirmed.")
    order = session.get(Order, delivery.order_id)
    if order is None or order.status != STATUS_APPROVED:
        raise DeliveryError("The linked order is not approved.")
    delivery.status = "CONFIRMED"
    delivery.dispatch_date = confirmed_at or datetime.now()
    delivery.confirmed_at = confirmed_at or datetime.now()
    delivery.receiver_name = receiver_name.strip() or None
    session.flush()
    delivered = delivered_quantities(session, order.id, include_drafts=False)
    order_items = session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    quantities = [delivered.get(item.id, 0) for item in order_items]
    if quantities and all(qty >= item.qty for item, qty in zip(order_items, quantities)):
        order.fulfillment_status = "DELIVERED"
    elif any(quantities):
        order.fulfillment_status = "PARTIALLY_DELIVERED"
    else:
        order.fulfillment_status = "OPEN"
    audit.record(
        session, actor_id=actor_id, action="CONFIRM", entity_type="DELIVERY",
        entity_id=delivery.id,
        changes={"status": "CONFIRMED", "order_fulfillment": order.fulfillment_status},
    )
    session.flush()
    return delivery
