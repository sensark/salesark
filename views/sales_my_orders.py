from html import escape

import streamlit as st

from erp.auth import require_role
from erp.db import session_scope
from erp.models import ORDER_STATUSES, ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER, STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED
from erp.services import orders as order_service
from erp.services.orders import OrderError
from erp.ui.components import badge, compact_currency, currency, kpi_row, page_header, section

user = require_role(ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER)
page_header("My Orders", "Track the status of orders you have submitted.", "Sales Workspace")

with session_scope() as session:
    orders = order_service.list_orders(session, sales_person_id=user.id, limit=1000)

approved = [o for o in orders if o.status == STATUS_APPROVED]
kpi_row([
    ("Approved revenue", compact_currency(float(sum(o.total for o in approved))), f"{len(approved)} orders"),
    ("Pending", str(sum(o.status == STATUS_PENDING for o in orders)), "Awaiting admin", "amber"),
    ("Rejected", str(sum(o.status == STATUS_REJECTED for o in orders)), "Review feedback", "navy"),
    ("Discount given", compact_currency(float(sum(o.discount_total for o in approved))), "On approved orders", "green"),
])

section("Orders")
f1, f2, f3 = st.columns([1, 2, 1.3], vertical_alignment="bottom")
status = f1.selectbox("Status", ["All", *ORDER_STATUSES])
term = f2.text_input("Search by order number or customer").strip().lower()
sort_order = f3.selectbox(
    "Sort orders", ["Newest", "Oldest", "Highest value", "Lowest value"]
)
shown = [
    o for o in orders
    if (status == "All" or o.status == status)
    and (not term or term in o.order_no.lower() or term in o.customer.name.lower())
]
shown.sort(key={
    "Newest": lambda order: order.created_at,
    "Oldest": lambda order: order.created_at,
    "Highest value": lambda order: order.total,
    "Lowest value": lambda order: order.total,
}[sort_order], reverse=sort_order in {"Newest", "Highest value"})
st.caption(f"{len(shown)} orders")

for o in shown[:100]:
    title = f"{o.order_no}  |  {o.customer.name}  |  {currency(float(o.total))}  |  {o.status}"
    with st.expander(title):
        st.markdown(
            f"{badge(o.status)} &nbsp; Placed {o.created_at:%d %b %Y %H:%M}"
            + (f" &nbsp;|&nbsp; Decided {o.decided_at:%d %b %Y %H:%M}" if o.decided_at else ""),
            unsafe_allow_html=True,
        )
        if o.rejection_reason:
            st.markdown(f'<div class="hint warn">Rejection reason: {escape(o.rejection_reason)}</div>',
                        unsafe_allow_html=True)
        st.dataframe(
            [
                {"Product": i.product.name, "Qty": i.qty, "Unit price": float(i.unit_price),
                 "Discount %": float(i.discount_pct), "Line total": float(i.line_total)}
                for i in o.items
            ],
            hide_index=True,
            column_config={
                "Unit price": st.column_config.NumberColumn(format="₹%.2f"),
                "Line total": st.column_config.NumberColumn(format="₹%.2f"),
                "Discount %": st.column_config.NumberColumn(format="%.0f%%"),
            },
        )
        st.markdown(
            f"Subtotal {currency(float(o.subtotal))} &nbsp;|&nbsp; Discount -{currency(float(o.discount_total))}"
            f" &nbsp;|&nbsp; Advance {float(o.advance_payment_pct):.0f}%"
            f" ({currency(float(o.total * o.advance_payment_pct / 100))})"
            f" &nbsp;|&nbsp; **Total {currency(float(o.total))}**"
        )
        if o.status in {STATUS_PENDING, STATUS_APPROVED}:
            reason = st.text_input("Cancellation reason", key=f"cancel_order_reason_{o.id}")
            if st.button("Cancel order", key=f"cancel_order_{o.id}", disabled=not reason.strip()):
                try:
                    with session_scope() as session:
                        order_service.cancel_order(session, o.id, user.id, reason)
                    st.success(f"Order {o.order_no} cancelled.")
                    st.rerun()
                except OrderError as exc:
                    st.error(str(exc))
if len(shown) > 100:
    st.caption("Showing the 100 most recent matching orders.")
