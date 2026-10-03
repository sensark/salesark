
from decimal import Decimal

import pytest

from erp.models import InventoryMovement, ROLE_ACCOUNTS, ROLE_WAREHOUSE, SalesInvoice, User
from erp.services import deliveries, payments
from erp.services.orders import CartLine, approve_order, place_order


def test_partial_deliveries_do_not_deduct_stock_twice(session, data):
    warehouse = User(username="wh", name="Warehouse", email="w@example.com", password_hash="x",
                     role=ROLE_WAREHOUSE)
    session.add(warehouse)
    session.flush()
    order = place_order(session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
                        lines=[CartLine(data["pen"].id, 20)])
    approve_order(session, order.id, data["admin"].id)
    session.flush()
    session.refresh(data["pen"])
    assert data["pen"].stock == 80

    item_id = order.items[0].id
    first = deliveries.create_delivery(session, order_id=order.id, actor_id=warehouse.id,
                                       quantities={item_id: 12})
    deliveries.confirm_delivery(session, first.id, warehouse.id, receiver_name="Dock 4")
    session.refresh(order)
    assert order.fulfillment_status == "PARTIALLY_DELIVERED"
    second = deliveries.create_delivery(session, order_id=order.id, actor_id=warehouse.id,
                                        quantities={item_id: 8})
    deliveries.confirm_delivery(session, second.id, warehouse.id)
    session.refresh(order)
    assert order.fulfillment_status == "DELIVERED"
    assert deliveries.open_order_items(session, order.id) == [(order.items[0], 0)]
    session.refresh(data["pen"])
    assert data["pen"].stock == 80
    assert session.query(InventoryMovement).filter_by(source_type="ORDER_APPROVAL").count() == 1


def test_cannot_overdeliver_or_double_claim_order_qty(session, data):
    warehouse = User(username="wh2", name="Warehouse", email="w2@example.com", password_hash="x",
                     role=ROLE_WAREHOUSE)
    session.add(warehouse)
    session.flush()
    order = place_order(session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
                        lines=[CartLine(data["pen"].id, 10)])
    approve_order(session, order.id, data["admin"].id)
    item_id = order.items[0].id
    deliveries.create_delivery(session, order_id=order.id, actor_id=warehouse.id,
                               quantities={item_id: 7})
    with pytest.raises(deliveries.DeliveryError):
        deliveries.create_delivery(session, order_id=order.id, actor_id=warehouse.id,
                                   quantities={item_id: 4})


def test_sales_role_cannot_create_delivery(session, data):
    order = place_order(session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
                        lines=[CartLine(data["pen"].id, 1)])
    approve_order(session, order.id, data["admin"].id)
    with pytest.raises(deliveries.DeliveryError):
        deliveries.create_delivery(session, order_id=order.id, actor_id=data["sales"].id,
                                   quantities={order.items[0].id: 1})


def test_advance_payment_is_required_before_dispatch(session, data):
    accounts = User(username="advance_accounts", name="Accounts", email="advance@example.com",
                    password_hash="x", role=ROLE_ACCOUNTS)
    warehouse = User(username="advance_wh", name="Warehouse", email="advance-wh@example.com",
                     password_hash="x", role=ROLE_WAREHOUSE)
    session.add_all([accounts, warehouse])
    session.flush()
    order = place_order(
        session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
        lines=[CartLine(data["pen"].id, 10)], advance_payment_pct=Decimal("25"),
    )
    approve_order(session, order.id, data["admin"].id)
    invoice = session.query(SalesInvoice).filter_by(order_id=order.id).one()
    required = (order.total * Decimal("0.25")).quantize(Decimal("0.01"))

    assert deliveries.open_order_items(session, order.id) == []
    waiting = deliveries.list_orders_waiting_for_advance(session)
    assert [(row[0].id, row[1], row[2]) for row in waiting] == [
        (order.id, required, Decimal("0.00"))
    ]
    with pytest.raises(deliveries.DeliveryError, match="advance payment"):
        deliveries.create_delivery(
            session, order_id=order.id, actor_id=warehouse.id,
            quantities={order.items[0].id: order.items[0].qty},
        )

    payment = payments.create_payment(
        session, customer_id=data["customer"].id, actor_id=accounts.id,
        amount=required, method="BANK_TRANSFER",
    )
    payments.allocate_payment(
        session, payment_id=payment.id, actor_id=accounts.id,
        allocations={invoice.id: required},
    )
    assert deliveries.open_order_items(session, order.id)[0][1] == order.items[0].qty
    assert deliveries.list_orders_waiting_for_advance(session) == []
