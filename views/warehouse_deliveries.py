import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from erp.auth import require_role
from erp.db import session_scope
from erp.models import Delivery, ROLE_ADMIN, ROLE_WAREHOUSE
from erp.services import deliveries
from erp.services.deliveries import DeliveryError
from erp.ui.components import page_header, section

user = require_role(ROLE_ADMIN, ROLE_WAREHOUSE)
page_header("Deliveries", "Dispatch approved orders in full or partial quantities.", "Warehouse")

if message := st.session_state.pop("delivery_flash", None):
    st.success(message)

with session_scope() as session:
    ready = deliveries.list_ready_orders(session)
    order_rows = [(o.id, o.order_no, o.customer.name, o.total) for o in ready]
    waiting_for_advance = deliveries.list_orders_waiting_for_advance(session)
    drafts = list(session.scalars(
        select(Delivery).where(Delivery.status == "DRAFT")
        .options(selectinload(Delivery.items)).order_by(Delivery.created_at)
    ))

section("Open approved orders")
if not order_rows:
    if waiting_for_advance:
        st.info("Approved orders are waiting for their required advance payment.")
        st.dataframe(
            [
                {
                    "Order": order.order_no,
                    "Customer": order.customer.name,
                    "Required advance": float(required),
                    "Received": float(paid),
                    "Remaining": float(required - paid),
                }
                for order, required, paid in waiting_for_advance
            ],
            hide_index=True,
            column_config={
                "Required advance": st.column_config.NumberColumn(format="₹%.2f"),
                "Received": st.column_config.NumberColumn(format="₹%.2f"),
                "Remaining": st.column_config.NumberColumn(format="₹%.2f"),
            },
        )
    else:
        st.info("There are no approved orders with quantities remaining to dispatch.")
else:
    selected = st.selectbox(
        "Order", order_rows,
        format_func=lambda row: f"{row[1]} · {row[2]} · INR {row[3]:,.2f}",
    )
    with session_scope() as session:
        open_lines = deliveries.open_order_items(session, selected[0])
        line_rows = [(item.id, item.product.name, item.qty, remaining) for item, remaining in open_lines]
    with st.form(f"dispatch_{selected[0]}"):
        quantities = {}
        for item_id, name, ordered, remaining in line_rows:
            col1, col2, col3 = st.columns([2, 1, 1])
            col1.write(name)
            col2.caption(f"Order qty {ordered}")
            quantities[item_id] = col3.number_input(
                "Dispatch qty", min_value=0, max_value=remaining, value=remaining,
                key=f"dispatch_qty_{item_id}",
            )
        a, b = st.columns(2)
        transport = a.text_input("Carrier / transport")
        tracking = b.text_input("Tracking / docket number")
        notes = st.text_input("Dispatch notes")
        if st.form_submit_button("Create dispatch draft", type="primary"):
            try:
                with session_scope() as session:
                    delivery = deliveries.create_delivery(
                        session, order_id=selected[0], actor_id=user.id,
                        quantities={item_id: int(qty) for item_id, qty in quantities.items() if qty},
                        transport_name=transport, tracking_number=tracking, notes=notes,
                    )
                    delivery_no = delivery.delivery_no
                st.session_state["delivery_flash"] = f"Dispatch {delivery_no} saved as draft."
                st.rerun()
            except DeliveryError as exc:
                st.error(str(exc))

section("Draft dispatches")
if not drafts:
    st.caption("No dispatch drafts need confirmation.")
else:
    with st.container(border=True):
        f1, f2 = st.columns([2, 1], vertical_alignment="bottom")
        draft_search = f1.text_input("Search dispatch drafts", placeholder="Delivery or order number")
        draft_sort = f2.selectbox("Sort drafts", ["Newest", "Oldest"])
    drafts = [d for d in drafts if not draft_search.strip()
              or draft_search.casefold() in d.delivery_no.casefold()
              or draft_search.casefold() in str(d.order_id)]
    drafts.sort(key=lambda d: d.created_at, reverse=draft_sort == "Newest")
for delivery in drafts:
    with st.container(border=True):
        st.markdown(f"**{delivery.delivery_no}** · Order #{delivery.order_id} · "
                    f"{len(delivery.items)} product lines · {delivery.transport_name or 'No carrier'}")
        receiver = st.text_input("Received by", key=f"receiver_{delivery.id}")
        if st.button("Confirm dispatch", key=f"confirm_{delivery.id}", type="primary"):
            try:
                with session_scope() as session:
                    deliveries.confirm_delivery(
                        session, delivery.id, user.id, receiver_name=receiver
                    )
                st.session_state["delivery_flash"] = (
                    f"Dispatch {delivery.delivery_no} confirmed. Inventory was already deducted on approval."
                )
                st.rerun()
            except DeliveryError as exc:
                st.error(str(exc))
