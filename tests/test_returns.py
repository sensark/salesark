from decimal import Decimal

import pytest

from erp.models import ROLE_ACCOUNTS, ROLE_SALES_MANAGER, ROLE_WAREHOUSE, SalesInvoice, User
from erp.services import deliveries, invoices, returns
from erp.services.orders import CartLine, approve_order, place_order


def _issued_invoice(session, data):
    accounts = User(username="returnacct", name="Accounts", email="ra@example.com", password_hash="x",
                    role=ROLE_ACCOUNTS)
    manager = User(username="returnmgr", name="Manager", email="rm@example.com", password_hash="x",
                   role=ROLE_SALES_MANAGER)
    warehouse = User(username="returnwh", name="Warehouse", email="rw@example.com", password_hash="x",
                     role=ROLE_WAREHOUSE)
    session.add_all([accounts, manager, warehouse])
    session.flush()
    data["pen"].gst_rate = Decimal("18")
    data["customer"].state = "West Bengal"
    order = place_order(session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
                        lines=[CartLine(data["pen"].id, 10)])
    approve_order(session, order.id, data["admin"].id)
    delivery = deliveries.create_delivery(session, order_id=order.id, actor_id=warehouse.id,
                                         quantities={order.items[0].id: 10})
    deliveries.confirm_delivery(session, delivery.id, warehouse.id)
    invoice = session.query(SalesInvoice).filter_by(order_id=order.id).one()
    return accounts, manager, warehouse, order, invoice


def test_return_to_received_credit_note_reduces_outstanding(session, data):
    accounts, manager, warehouse, order, invoice = _issued_invoice(session, data)
    item = invoice.items[0]
    sales_return = returns.create_return(
        session, invoice_id=invoice.id, actor_id=data["sales"].id,
        quantities={item.id: 2}, reason="DAMAGED",
    )
    with pytest.raises(returns.ReturnError):
        returns.create_return(session, invoice_id=invoice.id, actor_id=data["sales"].id,
                              quantities={item.id: 9}, reason="DAMAGED")
    returns.decide_return(session, sales_return.id, manager.id, approve=True)
    before_stock = data["pen"].stock
    returns.receive_return(session, sales_return.id, warehouse.id)
    assert data["pen"].stock == before_stock + 2
    note = returns.create_credit_note(session, sales_return.id, accounts.id)
    assert note.note_no.startswith("CN-")
    returns.issue_credit_note(session, note.id, accounts.id)
    assert note.status == "ISSUED"
    assert invoice.credit_total == note.total
    assert invoice.balance_due == invoice.total - note.total


def test_return_permissions_and_credit_note_requires_received_goods(session, data):
    accounts, manager, warehouse, _, invoice = _issued_invoice(session, data)
    sales_return = returns.create_return(
        session, invoice_id=invoice.id, actor_id=data["sales"].id,
        quantities={invoice.items[0].id: 1}, reason="WRONG_PRODUCT",
    )
    with pytest.raises(returns.ReturnError):
        returns.decide_return(session, sales_return.id, data["sales"].id, approve=True)
    with pytest.raises(returns.ReturnError):
        returns.create_credit_note(session, sales_return.id, accounts.id)


def test_debit_note_increases_invoice_balance(session, data):
    accounts, _, _, _, invoice = _issued_invoice(session, data)
    previous_balance = invoice.balance_due
    note = returns.create_debit_note(
        session, invoice_id=invoice.id, invoice_item_id=invoice.items[0].id,
        actor_id=accounts.id, taxable_amount=Decimal("100"), reason="Freight adjustment",
    )
    returns.issue_credit_note(session, note.id, accounts.id)
    assert note.note_type == "DEBIT"
    assert note.note_no.startswith("DBN-")
    assert invoice.debit_total == note.total
    assert invoice.balance_due == previous_balance + note.total
    assert invoice.status == "ISSUED"
