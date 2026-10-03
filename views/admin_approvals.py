from html import escape
from datetime import date

import streamlit as st
from sqlalchemy import select

from erp.auth import require_role
from erp.db import session_scope
from erp.models import ORDER_STATUSES, ROLE_ADMIN, ROLE_SALES_MANAGER, STATUS_PENDING, SalesInvoice
from erp.services import emails
from erp.services import orders as order_service
from erp.ui.components import badge, compact_currency, currency, hint, kpi_row, page_header

admin = require_role(ROLE_ADMIN, ROLE_SALES_MANAGER)
page_header("Order Approvals", "Review pending orders. Approval deducts stock and emails the customer.", "Administration")

for level, msg in st.session_state.pop("approval_flash", []):
    getattr(st, level)(msg)

with session_scope() as session:
    pending = order_service.list_orders(
        session,
        status=STATUS_PENDING,
        required_approver_role=None if admin.is_admin else "sales_manager",
        limit=500,
    )
    blocked = {o.id: order_service.stock_shortages(o) for o in pending}

with st.container(border=True):
    query = st.text_input(
        "Search orders",
        placeholder="Order number, customer, company, salesperson, SKU or product",
        key="approval_search",
    )
    customer_names = {o.customer_id: o.customer.name for o in pending}
    salesperson_names = {o.sales_person_id: o.sales_person.name for o in pending}
    c1, c2, c3, c4 = st.columns(
        [1.2, 1.2, 1, 1.4], vertical_alignment="bottom"
    )
    selected_customers = c1.multiselect(
        "Customer", sorted(customer_names),
        format_func=lambda customer_id: customer_names[customer_id],
        key="approval_customers",
    )
    selected_salespeople = c2.multiselect(
        "Salesperson", sorted(salesperson_names),
        format_func=lambda user_id: salesperson_names[user_id],
        key="approval_salespeople",
    )
    selected_regions = c3.multiselect(
        "Region", sorted({o.customer.region for o in pending}), key="approval_regions",
    )
    pending_dates = [o.created_at.date() for o in pending]
    min_date = min(pending_dates) if pending_dates else date.today()
    max_date = max(pending_dates) if pending_dates else date.today()
    selected_dates = c4.date_input(
        "Placed between", (min_date, max_date), min_value=min_date, max_value=max_date,
        key="approval_dates",
    )
    c5, c6 = st.columns(2, vertical_alignment="bottom")
    risk = c5.selectbox(
        "Risk", ["All", "Stock unavailable", "Low stock", "Credit review"],
        key="approval_risk",
    )
    sort_order = c6.selectbox(
        "Sort by", ["Oldest", "Newest", "Highest value", "Lowest value"]
    )
    start_date, end_date = (
        selected_dates if isinstance(selected_dates, tuple) and len(selected_dates) == 2
        else (min_date, max_date)
    )

filtered_pending = order_service.filter_approval_queue(
    pending,
    search=query,
    customer_ids=set(selected_customers),
    salesperson_ids=set(selected_salespeople),
    regions=set(selected_regions),
    start_date=start_date,
    end_date=end_date,
    risk=risk,
    shortages_by_order=blocked,
)
filtered_pending.sort(key={
    "Oldest": lambda order: order.created_at,
    "Newest": lambda order: -order.created_at.timestamp(),
    "Highest value": lambda order: -order.total,
    "Lowest value": lambda order: order.total,
}[sort_order])
filtered_blocked = {o.id: blocked[o.id] for o in filtered_pending}

kpi_row([
    ("Pending orders", str(len(filtered_pending)), f"{len(pending)} before filters", "amber"),
    ("Pending value", compact_currency(float(sum(o.total for o in filtered_pending))), "Filtered order value"),
    ("Blocked by stock", str(sum(bool(v) for v in filtered_blocked.values())), "Need replenishment", "navy"),
    ("Discount requested", compact_currency(float(sum(o.discount_total for o in filtered_pending))), "Filtered orders", "green"),
])

tab_pending, tab_history = st.tabs([f"Pending ({len(filtered_pending)})", "Decision history"])

with tab_pending:
    if not filtered_pending:
        if pending:
            st.info("No pending orders match these filters.")
        else:
            st.success("All caught up. There are no orders awaiting approval.")
    for o in sorted(filtered_pending, key=lambda x: x.created_at):
        shortages = filtered_blocked[o.id]
        with st.container(border=True):
            h1, h2 = st.columns([3, 1])
            h1.markdown(
                f'<div class="approval-card-title">{escape(o.order_no)} &nbsp;{badge(o.status)}</div>'
                f'<div class="approval-card-meta">{escape(o.customer.name)}'
                f'{" · " + escape(o.customer.company) if o.customer.company else ""} · '
                f'{escape(o.customer.region)} · {escape(o.sales_person.name)} · '
                f'{o.created_at:%d %b %Y %H:%M}</div>',
                unsafe_allow_html=True,
            )
            h2.markdown(
                f'<div class="approval-card-total">{currency(float(o.total))}</div>'
                f'<div class="approval-card-discount">saves {currency(float(o.discount_total))}</div>'
                f'<div class="approval-card-discount">advance {float(o.advance_payment_pct):.0f}% · '
                f'{currency(float(o.total * o.advance_payment_pct / 100))}</div>',
                unsafe_allow_html=True,
            )
            st.dataframe(
                [
                    {
                        "Product": i.product.name, "SKU": i.product.sku, "Qty": i.qty,
                        "In stock": i.product.stock, "Stock after": i.product.stock - i.qty,
                        "Unit price": float(i.unit_price), "Discount %": float(i.discount_pct),
                        "Line total": float(i.line_total),
                        "Stock status": (
                            "Insufficient" if i.product.stock < i.qty
                            else "Low" if i.product.stock - i.qty <= i.product.reorder_level else "OK"
                        ),
                    }
                    for i in o.items
                ],
                hide_index=True,
                column_config={
                    "Unit price": st.column_config.NumberColumn(format="₹%.2f"),
                    "Line total": st.column_config.NumberColumn(format="₹%.2f"),
                    "Discount %": st.column_config.NumberColumn(format="%.0f%%"),
                },
            )
            if o.notes:
                st.markdown(f'<div class="hint">Sales note: {escape(o.notes)}</div>', unsafe_allow_html=True)
            if o.credit_limit_exceeded:
                hint("Customer credit limit would be exceeded; manager approval is required.", "warn")
            if shortages:
                hint("Cannot approve: insufficient stock for "
                     + "; ".join(f"{n} (need {r}, have {a})" for n, r, a in shortages), "warn")
            elif any(i.product.stock - i.qty <= i.product.reorder_level for i in o.items):
                hint("Approving will bring one or more products to or below the reorder level.")

            a1, a2, a3 = st.columns([1, 2.4, 1])
            if a1.button("Approve", key=f"ap_{o.id}", type="primary", width="stretch",
                         disabled=bool(shortages)):
                flash = []
                try:
                    with session_scope() as session:
                        order_service.approve_order(session, o.id, admin.id)
                except order_service.OrderError as exc:
                    flash.append(("error", str(exc)))
                else:
                    with session_scope() as session:
                        invoice = session.scalar(select(SalesInvoice).where(SalesInvoice.order_id == o.id))
                        invoice_no = invoice.invoice_no if invoice else ""
                    with st.spinner("Sending confirmation email..."):
                        result = emails.send_order_confirmation(o.id)
                    flash.append(("success", f"Order {o.order_no} approved, stock updated, and invoice "
                                              f"{invoice_no} generated."))
                    if result.skipped:
                        flash.append(("info", "Email sending is disabled; the confirmation was logged only."))
                    elif not result.ok:
                        flash.append(("warning", f"Confirmation email failed: {result.error}. "
                                                 "You can resend it from the Email Log."))
                st.session_state["approval_flash"] = flash
                st.rerun()
            reason = a2.text_input("Rejection reason", key=f"rr_{o.id}", label_visibility="collapsed",
                                   placeholder="Reason for rejection (required to reject)")
            if a3.button("Reject", key=f"rj_{o.id}", width="stretch"):
                try:
                    with session_scope() as session:
                        order_service.reject_order(session, o.id, admin.id, reason)
                    st.session_state["approval_flash"] = [("success", f"Order {o.order_no} rejected.")]
                    st.rerun()
                except order_service.OrderError as exc:
                    st.error(str(exc))

with tab_history:
    status = st.selectbox("Status", [s for s in ORDER_STATUSES if s != STATUS_PENDING], key="hist_status")
    with session_scope() as session:
        decided = order_service.list_orders(session, status=status, limit=300)
        rows = [
            {
                "Order": o.order_no, "Customer": o.customer.name, "Sales person": o.sales_person.name,
                "Total": float(o.total), "Placed": o.created_at, "Decided": o.decided_at,
                "Decided by": o.decided_by.name if o.decided_by else "", "Reason": o.rejection_reason or "",
            }
            for o in decided
        ]
    st.dataframe(
        rows, hide_index=True, height=480,
        column_config={
            "Total": st.column_config.NumberColumn(format="₹%.2f"),
            "Placed": st.column_config.DatetimeColumn(format="DD MMM YYYY HH:mm"),
            "Decided": st.column_config.DatetimeColumn(format="DD MMM YYYY HH:mm"),
        },
    )
    st.caption("Confirmation emails can be resent from the Email Log page.")
