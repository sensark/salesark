from decimal import Decimal

import pandas as pd

from erp.models import ROLE_ACCOUNTS, ROLE_WAREHOUSE, User
from erp.services import analytics, deliveries, invoices, payments, reports
from erp.services.orders import CartLine, approve_order, place_order


def test_sales_fulfillment_tax_and_collection_reports(session, data):
    accounts = User(username="report_accounts", name="Accounts", email="ra@example.com",
                    password_hash="x", role=ROLE_ACCOUNTS)
    warehouse = User(username="report_wh", name="Warehouse", email="rw@example.com",
                     password_hash="x", role=ROLE_WAREHOUSE)
    session.add_all([accounts, warehouse])
    session.flush()
    data["pen"].gst_rate = Decimal("18")
    data["customer"].state = "West Bengal"
    order = place_order(session, sales_person_id=data["sales"].id,
                        customer_id=data["customer"].id,
                        lines=[CartLine(data["pen"].id, 20)])
    approve_order(session, order.id, data["admin"].id)

    sales = reports.sales_lines(session)
    assert len(sales) == 1
    assert sales.iloc[0]["taxable_amount"] == 190.0

    delivery = deliveries.create_delivery(
        session, order_id=order.id, actor_id=warehouse.id,
        quantities={order.items[0].id: 12},
    )
    deliveries.confirm_delivery(session, delivery.id, warehouse.id)
    delivery_frame = reports.delivery_lines(session)
    assert delivery_frame.iloc[0]["qty"] == 12

    from erp.models import SalesInvoice

    invoice = session.query(SalesInvoice).filter_by(order_id=order.id).one()
    invoice_frame = reports.invoice_lines(session)
    assert invoice_frame.iloc[0]["igst_amount"] == 0.0
    assert invoice_frame.iloc[0]["cgst_amount"] > 0

    receipt = payments.create_payment(
        session, customer_id=data["customer"].id, actor_id=accounts.id,
        amount=Decimal("100"), method="UPI",
    )
    payments.allocate_payment(
        session, payment_id=receipt.id, actor_id=accounts.id,
        allocations={invoice.id: Decimal("100")},
    )
    payments.reconcile_payment(session, receipt.id, accounts.id)
    collection_frame = reports.collection_lines(session)
    assert collection_frame.iloc[0]["allocated_amount"] == 100.0


def test_pareto_revenue_share_for_products_and_customers():
    items = pd.DataFrame({
        "product": ["A", "B", "C"], "category": ["X", "X", "Y"],
        "line_total": [80.0, 15.0, 5.0], "qty": [8, 2, 1],
    })
    orders = pd.DataFrame({
        "customer": ["A", "B", "C"], "company": [None, None, None],
        "region": ["N", "S", "E"], "total": [80.0, 15.0, 5.0],
        "order_id": [1, 2, 3],
    })

    product_pareto = analytics.pareto_products(items)
    customer_pareto = analytics.pareto_customers(orders)
    assert product_pareto.iloc[0]["cumulative_revenue_share"] == 0.8
    assert customer_pareto.iloc[-1]["cumulative_revenue_share"] == 1.0
