from decimal import Decimal

import pytest

from erp.models import (
    STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED, STATUS_CANCELLED,
    InventoryMovement, Notification, SalesInvoice,
)
from erp.services import orders as svc
from erp.services.orders import CartLine


def _place(session, data, lines):
    order = svc.place_order(session, sales_person_id=data["sales"].id, customer_id=data["customer"].id, lines=lines)
    session.commit()
    return order


def test_place_order_prices_from_db_and_notifies_admin(session, data):
    order = _place(session, data, [CartLine(data["pen"].id, 20), CartLine(data["pen"].id, 5)])
    assert order.status == STATUS_PENDING
    assert order.order_no.startswith("SO-2026-27-")
    assert len(order.items) == 1 and order.items[0].qty == 25
    assert order.items[0].discount_pct == Decimal("10")
    assert order.subtotal == Decimal("250.00")
    assert order.total == Decimal("225.00")
    assert order.discount_total == Decimal("25.00")
    assert session.query(Notification).filter_by(user_id=data["admin"].id).count() == 1

    next_order = svc.place_order(
        session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
        lines=[CartLine(data["pen"].id, 1)],
    )
    assert next_order.order_no.endswith("000002")


def test_place_order_rejects_bad_qty(session, data):
    with pytest.raises(svc.OrderError):
        svc.place_order(session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
                        lines=[CartLine(data["pen"].id, 0)])


def test_order_over_credit_limit_is_flagged_for_manager_review(session, data):
    data["customer"].credit_limit = Decimal("100.00")
    order = _place(session, data, [CartLine(data["pen"].id, 20)])
    assert order.credit_limit_exceeded is True


def test_approve_decrements_stock(session, data):
    order = _place(session, data, [CartLine(data["pen"].id, 30), CartLine(data["desk"].id, 2)])
    svc.approve_order(session, order.id, data["admin"].id)
    session.commit()
    session.refresh(data["pen"])
    session.refresh(data["desk"])
    assert data["pen"].stock == 70
    assert data["desk"].stock == 1
    assert svc.get_order(session, order.id).status == STATUS_APPROVED


def test_approve_insufficient_stock_is_atomic(session, data):
    order = _place(session, data, [CartLine(data["pen"].id, 30), CartLine(data["desk"].id, 5)])
    with pytest.raises(svc.InsufficientStockError):
        svc.approve_order(session, order.id, data["admin"].id)
    session.rollback()
    session.refresh(data["pen"])
    session.refresh(data["desk"])
    assert data["pen"].stock == 100
    assert data["desk"].stock == 3
    assert svc.get_order(session, order.id).status == STATUS_PENDING


def test_cannot_approve_twice(session, data):
    order = _place(session, data, [CartLine(data["pen"].id, 1)])
    svc.approve_order(session, order.id, data["admin"].id)
    session.commit()
    with pytest.raises(svc.OrderError):
        svc.approve_order(session, order.id, data["admin"].id)


def test_reject_requires_reason_and_notifies(session, data):
    order = _place(session, data, [CartLine(data["pen"].id, 1)])
    with pytest.raises(svc.OrderError):
        svc.reject_order(session, order.id, data["admin"].id, "  ")
    svc.reject_order(session, order.id, data["admin"].id, "Credit hold")
    session.commit()
    rejected = svc.get_order(session, order.id)
    assert rejected.status == STATUS_REJECTED and rejected.rejection_reason == "Credit hold"
    assert session.query(Notification).filter_by(user_id=data["sales"].id).count() == 1
    session.refresh(data["pen"])
    assert data["pen"].stock == 100


def test_cancelling_approved_unshipped_order_restores_stock(session, data):
    order = _place(session, data, [CartLine(data["pen"].id, 5)])
    svc.approve_order(session, order.id, data["admin"].id)
    session.flush()
    assert data["pen"].stock == 95
    cancelled = svc.cancel_order(session, order.id, data["sales"].id, "Customer changed the order")
    session.flush()
    assert cancelled.status == STATUS_CANCELLED
    assert session.query(SalesInvoice).filter_by(order_id=order.id).one().status == "CANCELLED"
    assert data["pen"].stock == 100
    movements = session.query(InventoryMovement).filter_by(source_id=order.id).all()
    assert sorted(m.qty_delta for m in movements) == [-5, 5]


def test_approval_queue_filters_search_and_risk(session, data):
    first = _place(session, data, [CartLine(data["pen"].id, 1)])
    second_customer = type(data["customer"])(
        name="Beta Mobility", email="beta@example.com", region="South",
        company="Beta Rehab Supplies", customer_status="ACTIVE",
    )
    session.add(second_customer)
    session.flush()
    second = svc.place_order(
        session, sales_person_id=data["sales"].id, customer_id=second_customer.id,
        lines=[CartLine(data["pen"].id, 2)],
    )
    session.flush()
    orders = svc.list_orders(session, status=STATUS_PENDING)
    shortages = {order.id: svc.stock_shortages(order) for order in orders}

    assert [o.id for o in svc.filter_approval_queue(orders, search="beta rehab")] == [second.id]
    assert [o.id for o in svc.filter_approval_queue(orders, regions={"South"})] == [second.id]
    assert [o.id for o in svc.filter_approval_queue(
        orders, customer_ids={second_customer.id}
    )] == [second.id]
    data["customer"].credit_limit = Decimal("1")
    first.credit_limit_exceeded = True
    assert [o.id for o in svc.filter_approval_queue(orders, risk="Credit review")] == [first.id]
    data["pen"].stock = 0
    shortages = {order.id: svc.stock_shortages(order) for order in orders}
    assert {o.id for o in svc.filter_approval_queue(
        orders, risk="Stock unavailable", shortages_by_order=shortages
    )} == {first.id, second.id}
