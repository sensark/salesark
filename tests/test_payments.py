from decimal import Decimal

import pytest

from erp.models import ROLE_ACCOUNTS, SalesInvoice, User
from erp.services import deliveries, invoices, payments
from erp.services.orders import CartLine, approve_order, place_order


def _issued_invoice(session, data, accounts):
    suffix = session.query(User).count()
    warehouse = User(username=f"whpay{suffix}", name="Warehouse", email=f"whpay{suffix}@example.com",
                     password_hash="x",
                     role="warehouse")
    session.add(warehouse)
    session.flush()
    order = place_order(session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
                        lines=[CartLine(data["pen"].id, 2)])
    approve_order(session, order.id, data["admin"].id)
    delivery = deliveries.create_delivery(session, order_id=order.id, actor_id=warehouse.id,
                                         quantities={order.items[0].id: 2})
    deliveries.confirm_delivery(session, delivery.id, warehouse.id)
    return session.query(SalesInvoice).filter_by(order_id=order.id).one()


def test_receipt_allocates_across_invoices(session, data):
    accounts = User(username="accpay", name="Accounts", email="accpay@example.com", password_hash="x",
                    role=ROLE_ACCOUNTS)
    session.add(accounts)
    session.flush()
    inv1 = _issued_invoice(session, data, accounts)
    inv2 = _issued_invoice(session, data, accounts)
    payment = payments.create_payment(
        session, customer_id=data["customer"].id, actor_id=accounts.id,
        amount=Decimal("20"), method="UPI", reference="UPI-01",
    )
    payments.allocate_payment(
        session, payment_id=payment.id, actor_id=accounts.id,
        allocations={inv1.id: Decimal("10"), inv2.id: Decimal("10")},
    )
    assert inv1.amount_paid == Decimal("10.00")
    assert inv2.amount_paid == Decimal("10.00")
    assert inv1.status == "PARTIALLY_PAID"
    assert payments.allocated_amount(session, payment.id) == Decimal("20.00")


def test_allocation_cannot_exceed_receipt_or_invoice_balance(session, data):
    accounts = User(username="accbound", name="Accounts", email="accbound@example.com", password_hash="x",
                    role=ROLE_ACCOUNTS)
    session.add(accounts)
    session.flush()
    invoice = _issued_invoice(session, data, accounts)
    payment = payments.create_payment(session, customer_id=data["customer"].id, actor_id=accounts.id,
                                      amount=Decimal("1000"), method="BANK_TRANSFER")
    with pytest.raises(payments.PaymentError):
        payments.allocate_payment(session, payment_id=payment.id, actor_id=accounts.id,
                                  allocations={invoice.id: invoice.balance_due + Decimal("1")})
    with pytest.raises(payments.PaymentError):
        payments.allocate_payment(session, payment_id=payment.id, actor_id=accounts.id,
                                  allocations={invoice.id: Decimal("1000")})


def test_non_accounts_cannot_record_receipt(session, data):
    with pytest.raises(payments.PaymentError):
        payments.create_payment(session, customer_id=data["customer"].id, actor_id=data["sales"].id,
                                amount=Decimal("1"), method="CASH")
