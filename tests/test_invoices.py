from decimal import Decimal

import pytest

from erp.models import ROLE_ACCOUNTS, ROLE_WAREHOUSE, SalesInvoice, User
from erp.services import deliveries, invoices
from erp.services.orders import CartLine, approve_order, place_order


def _setup(session, data, gst_rate=Decimal("18"), delivery_qty=20):
    accounts = User(username="accounts", name="Accounts", email="ac@example.com", password_hash="x",
                    role=ROLE_ACCOUNTS)
    warehouse = User(username="warehouse", name="Warehouse", email="wh@example.com", password_hash="x",
                     role=ROLE_WAREHOUSE)
    session.add_all([accounts, warehouse])
    session.flush()
    data["pen"].gst_rate = gst_rate
    data["customer"].state = "West Bengal"
    order = place_order(session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
                        lines=[CartLine(data["pen"].id, 20)])
    approve_order(session, order.id, data["admin"].id)
    delivery = deliveries.create_delivery(
        session, order_id=order.id, actor_id=warehouse.id,
        quantities={order.items[0].id: delivery_qty},
    )
    deliveries.confirm_delivery(session, delivery.id, warehouse.id)
    return accounts, warehouse, order, delivery


def test_partial_gst_invoices_cannot_exceed_delivered_quantity(session, data):
    accounts, _, order, delivery = _setup(session, data)
    invoice = session.query(SalesInvoice).filter_by(order_id=order.id).one()
    assert invoice.invoice_no.startswith("INV-")
    assert invoice.status == "ISSUED"
    assert invoice.taxable_total == order.taxable_total
    assert invoice.cgst_total == order.cgst_total
    assert invoice.sgst_total == order.sgst_total
    assert invoice.total == order.total
    assert invoice.items[0].qty == 20
    with pytest.raises(invoices.InvoiceError):
        invoices.create_invoice(session, delivery_id=delivery.id, actor_id=accounts.id,
                                quantities={delivery.items[0].id: 1})


def test_invoice_requires_confirmed_delivery_and_accounts_role(session, data):
    accounts, warehouse, order, delivery = _setup(session, data, delivery_qty=12)
    draft = deliveries.create_delivery(session, order_id=order.id, actor_id=warehouse.id,
                                       quantities={order.items[0].id: 1})
    with pytest.raises(invoices.InvoiceError):
        invoices.create_invoice(session, delivery_id=draft.id, actor_id=accounts.id,
                                quantities={draft.items[0].id: 1})
    with pytest.raises(invoices.InvoiceError):
        invoices.create_invoice(session, delivery_id=delivery.id, actor_id=warehouse.id,
                                quantities={delivery.items[0].id: 1})


def test_issued_invoice_cannot_be_cancelled_with_payment_activity(session, data):
    accounts, _, order, _ = _setup(session, data, gst_rate=Decimal("0"))
    invoice = session.query(SalesInvoice).filter_by(order_id=order.id).one()
    invoice.amount_paid = Decimal("1")
    with pytest.raises(invoices.InvoiceError):
        invoices.cancel_invoice(session, invoice.id, accounts.id, "wrong").status
