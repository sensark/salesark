from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from erp.models import ApprovalRule, ROLE_ADMIN, ROLE_SALES_MANAGER, STATUS_PENDING, User
from erp.services import quotations
from erp.services.orders import CartLine
from erp.services.quotations import QuotationError, convert_to_order, create_quotation, transition


def test_quote_lifecycle_and_idempotent_conversion(session, data):
    quote = create_quotation(
        session, customer_id=data["customer"].id, sales_person_id=data["sales"].id,
        lines=[CartLine(data["pen"].id, 12)],
    )
    assert quote.quotation_no.startswith("QT-")
    assert quote.total == Decimal("114.00")
    assert quote.items[0].gst_rate == Decimal("0.00")
    transition(session, quote.id, data["sales"].id, "submit")
    manager = User(username="manager", name="Manager", email="m@example.com", password_hash="x",
                   role=ROLE_SALES_MANAGER)
    session.add(manager)
    session.flush()
    transition(session, quote.id, manager.id, "approve")
    transition(session, quote.id, data["sales"].id, "send")
    transition(session, quote.id, data["sales"].id, "accept")
    order = convert_to_order(session, quote.id, manager.id)
    assert order.order_no.startswith("SO-")
    assert order.status == STATUS_PENDING
    assert order.total == quote.total
    assert order.items[0].unit_price == quote.items[0].unit_price
    assert convert_to_order(session, quote.id, manager.id).id == order.id


def test_quote_cannot_be_converted_before_acceptance(session, data):
    quote = create_quotation(
        session, customer_id=data["customer"].id, sales_person_id=data["sales"].id,
        lines=[CartLine(data["pen"].id, 1)],
    )
    with pytest.raises(QuotationError):
        convert_to_order(session, quote.id, data["sales"].id)


def test_salesperson_cannot_approve_quote(session, data):
    quote = create_quotation(
        session, customer_id=data["customer"].id, sales_person_id=data["sales"].id,
        lines=[CartLine(data["pen"].id, 1)],
    )
    transition(session, quote.id, data["sales"].id, "submit")
    with pytest.raises(QuotationError):
        transition(session, quote.id, data["sales"].id, "approve")


def test_converted_quote_inherits_admin_approval_rule(session, data):
    quote = create_quotation(
        session, customer_id=data["customer"].id, sales_person_id=data["sales"].id,
        lines=[CartLine(data["pen"].id, 25)],
    )
    transition(session, quote.id, data["sales"].id, "submit")
    manager = User(username="quote_manager", name="Manager", email="qm@example.com", password_hash="x",
                   role=ROLE_SALES_MANAGER)
    session.add(manager)
    session.add(ApprovalRule(name="High quote", rule_type="ORDER_VALUE", threshold=Decimal("1"),
                             approver_role=ROLE_ADMIN))
    session.flush()
    transition(session, quote.id, manager.id, "approve")
    transition(session, quote.id, data["sales"].id, "send")
    transition(session, quote.id, data["sales"].id, "accept")
    order = convert_to_order(session, quote.id, manager.id)
    assert order.required_approver_role == ROLE_ADMIN
    with pytest.raises(Exception):
        from erp.services.orders import approve_order
        approve_order(session, order.id, manager.id)


def test_expired_quotation_cannot_be_approved(session, data):
    quote = create_quotation(
        session, customer_id=data["customer"].id, sales_person_id=data["sales"].id,
        lines=[CartLine(data["pen"].id, 1)],
    )
    transition(session, quote.id, data["sales"].id, "submit")
    quote.valid_until = datetime.now() - timedelta(days=1)
    with pytest.raises(QuotationError):
        transition(session, quote.id, data["admin"].id, "approve")
    assert quotations.expire_due(session) == 1
    assert quote.status == "EXPIRED"
