import streamlit as st
from sqlalchemy import select

from erp.auth import require_role
from erp.db import session_scope
from erp.models import (
    Customer,
    DeliveryItem,
    Order,
    OrderItem,
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    SalesInvoice,
)
from erp.services import invoices
from erp.services import emails
from erp.services.invoices import InvoiceError
from erp.ui.components import currency, page_header, section

user = require_role(ROLE_ADMIN, ROLE_ACCOUNTS)
page_header("Sales Invoices", "Create GST invoices from confirmed delivery quantities.", "Accounts")

if message := st.session_state.pop("invoice_flash", None):
    st.success(message)

with session_scope() as session:
    deliveries_ready = invoices.list_invoiceable_deliveries(session)
    invoice_rows = list(session.execute(
        select(SalesInvoice, Customer, Order)
        .join(Customer, Customer.id == SalesInvoice.customer_id)
        .join(Order, Order.id == SalesInvoice.order_id)
        .order_by(SalesInvoice.invoice_date.desc())
    ))

section("Invoiceable deliveries")
if not deliveries_ready:
    st.info("There are no confirmed delivery quantities waiting to be invoiced.")
else:
    labels = []
    with session_scope() as session:
        for delivery in deliveries_ready:
            order = session.get(Order, delivery.order_id)
            customer = session.get(Customer, order.customer_id)
            labels.append((delivery.id, delivery.delivery_no, order.order_no, customer.name))
    delivery_choice = st.selectbox(
        "Confirmed delivery", labels,
        format_func=lambda row: f"{row[1]} · {row[2]} · {row[3]}",
    )
    with session_scope() as session:
        remaining = invoices.unbilled_quantities(session, delivery_choice[0])
        delivery_items = list(session.scalars(
            select(DeliveryItem).where(DeliveryItem.delivery_id == delivery_choice[0])
        ))
        line_data = []
        for line in delivery_items:
            order_item = session.get(OrderItem, line.order_item_id)
            line_data.append((line.id, order_item.product.name, remaining.get(line.id, 0)))
    with st.form("invoice_create", border=True):
        quantities = {}
        for item_id, name, qty_left in line_data:
            c1, c2 = st.columns([3, 1])
            c1.write(name)
            quantities[item_id] = c2.number_input(
                "Invoice qty", min_value=0, max_value=qty_left, value=qty_left,
                key=f"invoice_qty_{item_id}",
            )
        if st.form_submit_button("Create draft invoice", type="primary"):
            try:
                with session_scope() as session:
                    invoice = invoices.create_invoice(
                        session, delivery_id=delivery_choice[0], actor_id=user.id,
                        quantities={item_id: int(qty) for item_id, qty in quantities.items() if qty},
                    )
                    invoice_no = invoice.invoice_no
                st.session_state["invoice_flash"] = f"Draft invoice {invoice_no} created."
                st.rerun()
            except InvoiceError as exc:
                st.error(str(exc))

section("Invoices")
if not invoice_rows:
    st.info("No invoices have been created.")
else:
    with st.container(border=True):
        f1, f2, f3, f4 = st.columns(
            [1.4, 1, 1.4, 1], vertical_alignment="bottom"
        )
        invoice_search = f1.text_input("Search invoices", placeholder="Invoice, order or customer")
        statuses = sorted({invoice.status for invoice, _, _ in invoice_rows})
        invoice_status = f2.selectbox("Status", ["All", *statuses])
        invoice_customers = sorted({customer.name for _, customer, _ in invoice_rows})
        invoice_customer = f3.selectbox("Customer", ["All", *invoice_customers])
        invoice_sort = f4.selectbox("Sort by", ["Newest", "Oldest", "Highest total", "Lowest total"])
    needle = invoice_search.strip().casefold()
    visible_invoices = [
        row for row in invoice_rows
        if (invoice_status == "All" or row[0].status == invoice_status)
        and (invoice_customer == "All" or row[1].name == invoice_customer)
        and (not needle or needle in row[0].invoice_no.casefold()
             or needle in row[1].name.casefold() or needle in row[2].order_no.casefold())
    ]
    sort_key, reverse = {
        "Newest": (lambda row: row[0].invoice_date, True),
        "Oldest": (lambda row: row[0].invoice_date, False),
        "Highest total": (lambda row: row[0].total, True),
        "Lowest total": (lambda row: row[0].total, False),
    }[invoice_sort]
    visible_invoices.sort(key=sort_key, reverse=reverse)
    st.caption(f"{len(visible_invoices)} invoices")
for invoice, customer, order in visible_invoices if invoice_rows else []:
    with st.expander(f"{invoice.invoice_no} · {customer.name} · {invoice.status} · {currency(float(invoice.total))}"):
        st.write(f"Order {order.order_no} · Due {invoice.due_date:%d %b %Y}" if invoice.due_date else f"Order {order.order_no}")
        st.write(f"Taxable {currency(float(invoice.taxable_total))} · CGST {currency(float(invoice.cgst_total))} · "
                 f"SGST {currency(float(invoice.sgst_total))} · IGST {currency(float(invoice.igst_total))}")
        if invoice.status == "DRAFT" and st.button("Issue invoice", key=f"issue_{invoice.id}", type="primary"):
            try:
                with session_scope() as session:
                    invoices.issue_invoice(session, invoice.id, user.id)
                st.session_state["invoice_flash"] = f"Invoice {invoice.invoice_no} issued."
                st.rerun()
            except InvoiceError as exc:
                st.error(str(exc))
        if invoice.status in {"DRAFT", "ISSUED"}:
            reason = st.text_input("Cancellation reason", key=f"cancel_reason_{invoice.id}")
            if st.button("Cancel invoice", key=f"cancel_{invoice.id}", disabled=not reason.strip()):
                try:
                    with session_scope() as session:
                        invoices.cancel_invoice(session, invoice.id, user.id, reason)
                    st.session_state["invoice_flash"] = f"Invoice {invoice.invoice_no} cancelled."
                    st.rerun()
                except InvoiceError as exc:
                    st.error(str(exc))
        if invoice.status in {"ISSUED", "PARTIALLY_PAID", "PAID"}:
            try:
                html, subject, _ = emails.render_invoice(invoice.id)
                dl, send = st.columns(2)
                dl.download_button(
                    "Download invoice HTML", html, f"{invoice.invoice_no}.html", "text/html",
                    key=f"download_invoice_{invoice.id}",
                )
                if send.button("Email invoice", key=f"email_invoice_{invoice.id}"):
                    result = emails.send_invoice(invoice.id)
                    if result.ok:
                        st.success("Invoice email logged as delivered." if not result.skipped
                                   else "Invoice email is disabled; the message was logged only.")
                    else:
                        st.error(result.error or "Invoice email failed.")
            except ValueError as exc:
                st.error(str(exc))
