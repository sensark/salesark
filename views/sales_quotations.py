import streamlit as st
from sqlalchemy import select

from erp.auth import require_role
from erp.db import session_scope
from erp.models import Customer, ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER
from erp.services import emails, quotations
from erp.services.orders import CartLine
from erp.services.products import list_products
from erp.ui.components import currency, page_header

user = require_role(ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER)
page_header("Quotations", "Prepare customer pricing, route approval and convert accepted quotes.", "Sales Workspace")

if message := st.session_state.pop("quote_flash", None):
    st.success(message)

with session_scope() as session:
    customers = list(session.scalars(
        select(Customer).where(Customer.customer_status == "ACTIVE").order_by(Customer.name)
    ))
    products = list_products(session)
    quotes = quotations.list_quotations(
        session,
        sales_person_id=None if user.role in {ROLE_ADMIN, ROLE_SALES_MANAGER} else user.id,
    )

create_tab, manage_tab = st.tabs(["Create quotation", "Manage quotations"])
with create_tab:
    if not customers or not products:
        st.info("Add an active customer and products before creating a quotation.")
    else:
        customer = st.selectbox(
            "Customer", customers,
            format_func=lambda c: f"{c.name} · {c.company or c.email}",
        )
        cart: dict[int, int] = st.session_state.setdefault("quote_cart", {})
        col_product, col_qty, col_add = st.columns([2, 1, 1])
        product = col_product.selectbox(
            "Product", products, format_func=lambda p: f"{p.name} · {p.sku}"
        )
        qty = col_qty.number_input("Quantity", min_value=1, step=1, value=1)
        if col_add.button("Add line", width="stretch"):
            cart[product.id] = cart.get(product.id, 0) + int(qty)
            st.rerun()

        if cart:
            st.dataframe(
                [{"Product": next(p.name for p in products if p.id == pid), "Quantity": count}
                 for pid, count in cart.items()],
                hide_index=True,
            )
            valid_days = st.number_input("Valid for (days)", min_value=1, max_value=180, value=30)
            notes = st.text_area("Notes")
            terms = st.text_area("Terms and conditions")
            save_col, clear_col = st.columns(2)
            if save_col.button("Save draft", type="primary", width="stretch"):
                try:
                    with session_scope() as session:
                        quote = quotations.create_quotation(
                            session, customer_id=customer.id, sales_person_id=user.id,
                            lines=[CartLine(pid, count) for pid, count in cart.items()],
                            valid_days=int(valid_days), notes=notes, terms=terms,
                        )
                        quote_no = quote.quotation_no
                    cart.clear()
                    st.session_state["quote_flash"] = f"Quotation {quote_no} saved as draft."
                    st.rerun()
                except quotations.QuotationError as exc:
                    st.error(str(exc))
            if clear_col.button("Clear lines", width="stretch"):
                cart.clear()
                st.rerun()

with manage_tab:
    if not quotes:
        st.info("No quotations yet.")
    else:
        q1, q2, q3 = st.columns(
            [1.5, 1, 1], vertical_alignment="bottom"
        )
        quote_search = q1.text_input("Search quotations", placeholder="Quotation or customer")
        quote_status = q2.selectbox("Quotation status", ["All", *sorted({q.status for q in quotes})])
        quote_sort = q3.selectbox("Sort quotations", ["Newest", "Oldest", "Highest total"])
        customer_names = {customer.id: customer.name for customer in customers}
        visible_quotes = [
            quote for quote in quotes
            if (quote_status == "All" or quote.status == quote_status)
            and (not quote_search.strip()
                 or quote_search.casefold() in quote.quotation_no.casefold()
                 or quote_search.casefold() in customer_names.get(quote.customer_id, "").casefold())
        ]
        visible_quotes.sort(
            key=lambda quote: quote.total if quote_sort == "Highest total" else quote.created_at,
            reverse=quote_sort != "Oldest",
        )
        st.dataframe(
            [{"Quotation": q.quotation_no, "Customer": next(
                 (c.name for c in customers if c.id == q.customer_id), ""),
              "Status": q.status, "Valid until": q.valid_until, "Total": float(q.total),
              "Created": q.created_at} for q in visible_quotes],
            hide_index=True,
            column_config={
                "Total": st.column_config.NumberColumn(format="₹%.2f"),
                "Valid until": st.column_config.DateColumn(format="DD MMM YYYY"),
                "Created": st.column_config.DatetimeColumn(format="DD MMM YYYY HH:mm"),
            },
        )
        quote = st.selectbox(
            "Open quotation", visible_quotes,
            format_func=lambda q: f"{q.quotation_no} · {q.status}",
        )
        if quote is None:
            st.info("No quotations match the current filters.")
            st.stop()
        st.markdown(f"**{quote.status}** · {currency(float(quote.total))}")
        if quote.rejection_reason:
            st.warning(f"Rejection reason: {quote.rejection_reason}")
        if quote.items:
            st.dataframe(
                [{"Product": item.description, "Qty": item.qty, "Unit price": float(item.unit_price),
                  "Discount %": float(item.discount_pct), "Taxable": float(item.taxable_amount),
                  "GST": float(item.cgst_amount + item.sgst_amount + item.igst_amount + item.cess_amount),
                  "Line total": float(item.line_total)} for item in quote.items],
                hide_index=True,
                column_config={
                    "Unit price": st.column_config.NumberColumn(format="₹%.2f"),
                    "Taxable": st.column_config.NumberColumn(format="₹%.2f"),
                    "GST": st.column_config.NumberColumn(format="₹%.2f"),
                    "Line total": st.column_config.NumberColumn(format="₹%.2f"),
                    "Discount %": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

        actions = st.columns(4)
        if quote.status == "DRAFT" and actions[0].button("Submit", key=f"submit_{quote.id}"):
            action = "submit"
        elif quote.status == "SUBMITTED" and user.role in {ROLE_ADMIN, ROLE_SALES_MANAGER} and actions[0].button("Approve", key=f"approve_{quote.id}", type="primary"):
            action = "approve"
        elif quote.status == "APPROVED" and actions[0].button("Email quote", key=f"send_{quote.id}"):
            action = "send"
        elif quote.status == "SENT" and actions[0].button("Record customer acceptance", key=f"accept_{quote.id}"):
            action = "accept"
        elif quote.status == "ACCEPTED" and actions[0].button("Convert to order", key=f"convert_{quote.id}", type="primary"):
            action = "convert"
        else:
            action = ""

        if action:
            try:
                if action == "convert":
                    with session_scope() as session:
                        order = quotations.convert_to_order(session, quote.id, user.id)
                        order_no = order.order_no
                    st.session_state["quote_flash"] = f"Converted to pending order {order_no}."
                else:
                    with session_scope() as session:
                        quotations.transition(session, quote.id, user.id, action)
                    if action == "send":
                        result = emails.send_quotation(quote.id)
                        if not result.ok and not result.skipped:
                            st.warning(f"Quote status updated, but email failed: {result.error}")
                    st.session_state["quote_flash"] = f"Quotation {quote.quotation_no}: {action} complete."
                st.rerun()
            except quotations.QuotationError as exc:
                st.error(str(exc))

        if quote.status == "SUBMITTED" and user.role in {ROLE_ADMIN, ROLE_SALES_MANAGER}:
            reason = st.text_input("Rejection reason", key=f"quote_reason_{quote.id}")
            if actions[1].button("Reject", key=f"reject_{quote.id}", disabled=not reason.strip()):
                try:
                    with session_scope() as session:
                        quotations.transition(session, quote.id, user.id, "reject", reason=reason)
                    st.session_state["quote_flash"] = f"Quotation {quote.quotation_no} rejected."
                    st.rerun()
                except quotations.QuotationError as exc:
                    st.error(str(exc))
