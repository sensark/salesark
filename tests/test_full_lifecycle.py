from decimal import Decimal

from erp.models import ROLE_ACCOUNTS, ROLE_SALES_MANAGER, ROLE_WAREHOUSE, SalesInvoice, User
from erp.services import deliveries, invoices, payments, quotations, returns
from erp.services.orders import CartLine, approve_order


def test_quote_to_credit_note_lifecycle(session, data):
    manager = User(username="e2e_manager", name="Manager", email="e2e_manager@example.com",
                   password_hash="x", role=ROLE_SALES_MANAGER)
    accounts = User(username="e2e_accounts", name="Accounts", email="e2e_accounts@example.com",
                    password_hash="x", role=ROLE_ACCOUNTS)
    warehouse = User(username="e2e_warehouse", name="Warehouse", email="e2e_warehouse@example.com",
                     password_hash="x", role=ROLE_WAREHOUSE)
    session.add_all([manager, accounts, warehouse])
    session.flush()
    data["customer"].state = "West Bengal"
    data["pen"].gst_rate = Decimal("18")

    quote = quotations.create_quotation(
        session, customer_id=data["customer"].id, sales_person_id=data["sales"].id,
        lines=[CartLine(data["pen"].id, 10)],
    )
    quotations.transition(session, quote.id, data["sales"].id, "submit")
    quotations.transition(session, quote.id, manager.id, "approve")
    quotations.transition(session, quote.id, data["sales"].id, "send")
    quotations.transition(session, quote.id, data["sales"].id, "accept")
    order = quotations.convert_to_order(session, quote.id, manager.id)
    approve_order(session, order.id, manager.id)
    assert data["pen"].stock == 90

    delivery = deliveries.create_delivery(
        session, order_id=order.id, actor_id=warehouse.id,
        quantities={order.items[0].id: 6},
    )
    deliveries.confirm_delivery(session, delivery.id, warehouse.id)
    assert order.fulfillment_status == "PARTIALLY_DELIVERED"
    assert data["pen"].stock == 90

    invoice = session.query(SalesInvoice).filter_by(order_id=order.id).one()
    assert invoice.igst_total == Decimal("0.00")
    assert invoice.cgst_total > 0 and invoice.sgst_total > 0

    payment = payments.create_payment(
        session, customer_id=data["customer"].id, actor_id=accounts.id,
        amount=Decimal("10"), method="UPI", reference="DEMO-UPI-1",
    )
    payments.allocate_payment(
        session, payment_id=payment.id, actor_id=accounts.id,
        allocations={invoice.id: Decimal("10")},
    )
    payments.reconcile_payment(session, payment.id, accounts.id)

    request = returns.create_return(
        session, invoice_id=invoice.id, actor_id=data["sales"].id,
        quantities={invoice.items[0].id: 1}, reason="DAMAGED",
    )
    returns.decide_return(session, request.id, manager.id, approve=True)
    returns.receive_return(session, request.id, warehouse.id)
    note = returns.create_credit_note(session, request.id, accounts.id)
    returns.issue_credit_note(session, note.id, accounts.id)

    assert note.total == Decimal("11.22")
    assert invoice.amount_paid == Decimal("10.00")
    assert invoice.credit_total == note.total
    assert invoice.balance_due == invoice.total - invoice.amount_paid - note.total
    assert data["pen"].stock == 91
    assert request.status == "RECEIVED"
