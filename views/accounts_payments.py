from decimal import Decimal

import streamlit as st
from sqlalchemy import select

from erp.auth import require_role
from erp.db import session_scope
from erp.models import Customer, ROLE_ACCOUNTS, ROLE_ADMIN, SalesInvoice
from erp.services import payments
from erp.services.payments import PAYMENT_METHODS, PaymentError
from erp.ui.components import currency, page_header, section

user = require_role(ROLE_ADMIN, ROLE_ACCOUNTS)
page_header("Payments", "Record receipts and allocate them across open invoices.", "Accounts")

if message := st.session_state.pop("payment_flash", None):
    st.success(message)

with session_scope() as session:
    customers = list(session.scalars(select(Customer).where(Customer.customer_status == "ACTIVE").order_by(Customer.name)))
    invoices = list(session.scalars(
        select(SalesInvoice).where(SalesInvoice.status.in_(["ISSUED", "PARTIALLY_PAID"])).order_by(SalesInvoice.due_date)
    ))
    receipts = payments.list_payments(session)

section("New receipt")
if not customers:
    st.info("Add customers before recording payments.")
else:
    customer = st.selectbox("Customer", customers, format_func=lambda c: f"{c.name} · {c.company or c.email}")
    customer_invoices = [inv for inv in invoices if inv.customer_id == customer.id]
    with st.form("receipt_form", border=True):
        a, b, c = st.columns(3)
        amount = a.number_input("Receipt amount (INR)", min_value=0.01, step=100.0, value=1000.0)
        method = b.selectbox("Method", PAYMENT_METHODS)
        reference = c.text_input("Bank / UPI reference")
        notes = st.text_input("Notes")
        allocations = {}
        if customer_invoices:
            st.caption("Allocate this receipt; any unallocated remainder remains on account.")
            for invoice in customer_invoices:
                left, right = st.columns([2, 1])
                left.write(f"{invoice.invoice_no} · due {invoice.due_date:%d %b %Y} · balance {currency(float(invoice.balance_due))}" if invoice.due_date else f"{invoice.invoice_no} · balance {currency(float(invoice.balance_due))}")
                allocations[invoice.id] = right.number_input(
                    "Allocate", min_value=0.0, max_value=float(invoice.balance_due), value=0.0,
                    step=100.0, key=f"alloc_{invoice.id}",
                )
        else:
            st.info("No open invoices for this customer; the receipt can remain unallocated.")
        if st.form_submit_button("Record receipt", type="primary"):
            try:
                with session_scope() as session:
                    receipt = payments.create_payment(
                        session, customer_id=customer.id, actor_id=user.id,
                        amount=Decimal(str(amount)), method=method,
                        reference=reference, notes=notes,
                    )
                    to_allocate = {i: Decimal(str(v)) for i, v in allocations.items() if v}
                    if to_allocate:
                        payments.allocate_payment(
                            session, payment_id=receipt.id, actor_id=user.id, allocations=to_allocate,
                        )
                    receipt_no = receipt.receipt_no
                st.session_state["payment_flash"] = f"Receipt {receipt_no} recorded."
                st.rerun()
            except PaymentError as exc:
                st.error(str(exc))

section("Receipts")
if receipts:
    rows = []
    for receipt in receipts:
        with session_scope() as session:
            allocated = payments.allocated_amount(session, receipt.id)
        rows.append({"Receipt": receipt.receipt_no, "Date": receipt.payment_date,
                     "Customer": next((c.name for c in customers if c.id == receipt.customer_id), ""),
                     "Amount": float(receipt.amount), "Allocated": float(allocated),
                     "Unallocated": float(receipt.amount - allocated), "Method": receipt.method,
                     "Status": receipt.status})
    with st.container(border=True):
        f1, f2, f3, f4 = st.columns(
            [1.5, 1, 1, 1], vertical_alignment="bottom"
        )
        receipt_search = f1.text_input("Search receipts", placeholder="Receipt or customer")
        receipt_method = f2.selectbox("Method", ["All", *sorted({r["Method"] for r in rows})])
        receipt_status = f3.selectbox("Receipt status", ["All", *sorted({r["Status"] for r in rows})])
        receipt_sort = f4.selectbox("Sort receipts", ["Newest", "Oldest", "Highest amount"])
    rows = [r for r in rows
            if (not receipt_search.strip() or receipt_search.casefold() in r["Receipt"].casefold()
                or receipt_search.casefold() in r["Customer"].casefold())
            and (receipt_method == "All" or r["Method"] == receipt_method)
            and (receipt_status == "All" or r["Status"] == receipt_status)]
    rows.sort(key=lambda r: r["Amount"] if receipt_sort == "Highest amount" else r["Date"],
              reverse=receipt_sort != "Oldest")
    st.dataframe(rows, hide_index=True, column_config={
        "Amount": st.column_config.NumberColumn(format="₹%.2f"),
        "Allocated": st.column_config.NumberColumn(format="₹%.2f"),
        "Unallocated": st.column_config.NumberColumn(format="₹%.2f"),
        "Date": st.column_config.DatetimeColumn(format="DD MMM YYYY"),
    })
