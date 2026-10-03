from html import escape

import streamlit as st

from erp.auth import require_role
from erp.db import session_scope
from erp.models import REGIONS, ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER, Customer
from erp.services import customers as customer_service
from erp.ui.customer_form import customer_fields
from erp.services import emails
from erp.services import orders as order_service
from erp.services import products as product_service
from erp.services.discounts import discount_for, line_total, recommend
from erp.services.pricing import resolve_unit_price
from erp.ui.components import currency, hint, page_header, section

user = require_role(ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER)
cart: dict[int, int] = st.session_state.setdefault("cart", {})

page_header("New Order", "Select a customer, build the cart and submit for approval.", "Sales Workspace")

if flash := st.session_state.pop("order_flash", None):
    st.success(flash)


def tier_chips(tiers, qty: int) -> str:
    current = discount_for(tiers, qty)
    rec = recommend(tiers, 0, qty)
    chips = []
    for t in tiers:
        cls = "active" if t.discount_pct == current and qty >= t.min_qty else ""
        if rec and t.min_qty == rec.next_min_qty:
            cls = "next"
        chips.append(f'<span class="tier {cls}">{t.min_qty}+ units: {t.discount_pct:.0f}% off</span>')
    if not chips:
        return '<div class="tier-row"><span class="tier">No volume discounts on this product</span></div>'
    return f'<div class="tier-row">{"".join(chips)}</div>'


# ---------- Step 1: customer ----------
section("1. Customer")
with session_scope() as session:
    selected = session.get(Customer, st.session_state.get("order_customer_id") or 0)
    selected_label = f"{selected.name} - {selected.company or 'Individual'} ({selected.email})" if selected else None

if selected:
    c1, c2 = st.columns([5, 1])
    c1.markdown(
        f'<div class="hint ok">Ordering for <b>{escape(selected_label)}</b></div>', unsafe_allow_html=True
    )
    if c2.button("Change", width="stretch"):
        st.session_state.pop("order_customer_id")
        st.rerun()
else:
    tab_existing, tab_new = st.tabs(["Existing customer", "New customer"])
    with tab_existing:
        term = st.text_input("Search by name, company, email or phone", key="cust_search")
        with session_scope() as session:
            found = [(c.id, f"{c.name} - {c.company or 'Individual'} ({c.email})")
                     for c in customer_service.search(session, term)]
        if found:
            choice = st.selectbox("Customer", found, format_func=lambda x: x[1], index=None,
                                  placeholder="Choose a customer")
            if st.button("Use this customer", type="primary", disabled=choice is None):
                st.session_state["order_customer_id"] = choice[0]
                st.rerun()
        else:
            st.info("No customers match your search. Add them in the New customer tab.")
    with tab_new:
        with st.form("new_customer", clear_on_submit=False):
            a, b = st.columns(2)
            name = a.text_input("Full name *")
            email = b.text_input("Email *")
            company = a.text_input("Company")
            phone = b.text_input("Phone")
            region = a.selectbox("Region *", REGIONS)
            city = b.text_input("City")
            address = st.text_area("Address", height=70)
            extra_fields = customer_fields("order_new_customer")
            if st.form_submit_button("Create and select", type="primary"):
                try:
                    with session_scope() as session:
                        c = customer_service.create(
                            session, name=name, email=email, region=region, created_by_id=user.id,
                            company=company, phone=phone, city=city, address=address,
                            **extra_fields,
                        )
                        st.session_state["order_customer_id"] = c.id
                    st.rerun()
                except customer_service.CustomerError as exc:
                    st.error(str(exc))
    st.stop()

# ---------- Step 2: products ----------
left, right = st.columns([2.1, 1], gap="large")

with session_scope() as session:
    product_list = product_service.list_products(session)
    products = {p.id: p for p in product_list}

with left:
    section("2. Add products")
    with st.container(border=True):
        categories = sorted({p.category for p in product_list})
        f1, f2 = st.columns([1, 2])
        category = f1.selectbox("Category", ["All"] + categories)
        options = [p for p in product_list if category == "All" or p.category == category]
        product = f2.selectbox(
            "Product", options, format_func=lambda p: f"{p.name}  |  {p.sku}  |  {currency(float(p.unit_price))}",
        )
        if product:
            in_cart = cart.get(product.id, 0)
            q1, q2 = st.columns([1, 2])
            qty = q1.number_input("Quantity", min_value=1, value=1, step=1, key=f"qty_{product.id}")
            total_qty = in_cart + qty
            with session_scope() as session:
                current_product = session.get(type(product), product.id)
                unit_price = resolve_unit_price(
                    session, current_product, total_qty,
                    customer_id=selected.id, price_list_id=selected.price_list_id,
                ).unit_price
            pct = discount_for(product.tiers, total_qty)
            with q2:
                st.markdown(
                    f"<div style='padding-top:28px'>Unit {currency(float(unit_price))} &nbsp;|&nbsp; "
                    f"Stock <b>{product.stock}</b> &nbsp;|&nbsp; Discount at {total_qty} units: "
                    f"<b style='color:#FF7A00'>{pct:.0f}%</b></div>",
                    unsafe_allow_html=True,
                )
            st.markdown(tier_chips(product.tiers, total_qty), unsafe_allow_html=True)
            rec = recommend(product.tiers, unit_price, total_qty)
            if rec:
                hint(
                    f"Recommendation: {rec.message}. Line would be {currency(float(rec.next_line_total))} "
                    f"(+{currency(float(rec.extra_cost))} for {rec.extra_qty} more units)."
                )
            elif product.tiers:
                hint("Top discount tier reached for this product.", "ok")
            if total_qty > product.stock:
                hint(f"Only {product.stock} in stock. This order cannot be approved until stock is replenished.", "warn")
            elif product.stock - total_qty <= product.reorder_level:
                hint("Low stock: this order will bring stock below the reorder level.", "warn")
            if in_cart:
                st.caption(f"{in_cart} already in cart. Adding will increase the line quantity.")

            b1, b2, _ = st.columns([1, 1.4, 1.6])
            if b1.button("Add to cart", type="primary", width="stretch"):
                cart[product.id] = total_qty
                st.session_state.pop(f"cart_{product.id}", None)
                st.rerun()
            if rec and b2.button(f"Add {rec.next_min_qty - in_cart} (unlock {rec.next_discount_pct:.0f}%)",
                                 width="stretch"):
                cart[product.id] = rec.next_min_qty
                st.session_state.pop(f"cart_{product.id}", None)
                st.rerun()

    section("3. Cart")
    if not cart:
        st.info("The cart is empty. Add products above.")
    for pid in list(cart):
        p = products.get(pid)
        if p is None:
            cart.pop(pid)
            continue
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 1.1, 1.3, 0.8])
            with session_scope() as session:
                current_product = session.get(type(p), p.id)
                unit_price = resolve_unit_price(
                    session, current_product, cart[pid],
                    customer_id=selected.id, price_list_id=selected.price_list_id,
                ).unit_price
            c1.markdown(
                f"**{p.name}**  \n{p.sku} &middot; {p.category} &middot; "
                f"{currency(float(unit_price))} each"
            )
            new_qty = c2.number_input("Qty", min_value=1, value=cart[pid], step=1, key=f"cart_{pid}",
                                      label_visibility="collapsed")
            if new_qty != cart[pid]:
                cart[pid] = int(new_qty)
                st.rerun()
            pct = discount_for(p.tiers, cart[pid])
            c3.markdown(
                f"<div style='text-align:right'><b>{currency(float(line_total(unit_price, cart[pid], pct)))}</b>"
                f"<br><span style='color:#1E9E5A;font-size:13px'>{pct:.0f}% off</span></div>",
                unsafe_allow_html=True,
            )
            if c4.button("Remove", key=f"rm_{pid}", width="stretch"):
                cart.pop(pid)
                st.session_state.pop(f"cart_{pid}", None)
                st.rerun()
            rec = recommend(p.tiers, unit_price, cart[pid])
            if rec:
                h1, h2 = st.columns([4, 1.2])
                with h1:
                    hint(f"{rec.message} (+{currency(float(rec.extra_cost))}).")
                if h2.button("Apply", key=f"apply_{pid}", width="stretch"):
                    cart[pid] = rec.next_min_qty
                    st.session_state.pop(f"cart_{pid}", None)
                    st.rerun()
            if cart[pid] > p.stock:
                hint(f"Requested {cart[pid]} but only {p.stock} in stock.", "warn")
            elif p.stock - cart[pid] <= p.reorder_level:
                st.markdown('<span class="badge LOW">Low stock</span>', unsafe_allow_html=True)

# ---------- Summary ----------
with right:
    section("Order summary")
    lines = [order_service.CartLine(pid, q) for pid, q in cart.items()]
    subtotal = discount_total = taxable = tax_total = total = 0.0
    cgst = sgst = igst = cess = 0.0
    if lines:
        with session_scope() as session:
            priced = order_service.price_cart(session, lines, customer_id=selected.id)
            subtotal = float(sum(p.gross for p in priced))
            discount_total = float(sum(p.tax.discount for p in priced))
            taxable = float(sum(p.tax.taxable for p in priced))
            cgst = float(sum(p.tax.cgst for p in priced))
            sgst = float(sum(p.tax.sgst for p in priced))
            igst = float(sum(p.tax.igst for p in priced))
            cess = float(sum(p.tax.cess for p in priced))
            tax_total = cgst + sgst + igst + cess
            total = float(sum(p.tax.total for p in priced))
    units = sum(cart.values())
    st.markdown(
        f"""<div class="summary-card">
        <div class="row"><span>Customer</span><span>{escape(selected.name)}</span></div>
        <div class="row"><span>Lines / units</span><span>{len(cart)} / {units}</span></div>
        <div class="row"><span>Subtotal</span><span>{currency(subtotal)}</span></div>
        <div class="row save"><span>Discount</span><span>-{currency(discount_total)}</span></div>
        <div class="row"><span>Taxable value</span><span>{currency(taxable)}</span></div>
        <div class="row"><span>CGST / SGST</span><span>{currency(cgst)} / {currency(sgst)}</span></div>
        <div class="row"><span>IGST / Cess</span><span>{currency(igst)} / {currency(cess)}</span></div>
        <div class="row"><span>Total GST</span><span>{currency(tax_total)}</span></div>
        <div class="total"><span>Total</span><span>{currency(total)}</span></div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.write("")
    advance_payment_pct = st.number_input(
        "Advance payment (%)", min_value=0.0, max_value=100.0, step=5.0,
        value=0.0, help="Required collection before warehouse dispatch.",
    )
    notes = st.text_area("Notes for the approver", height=90, max_chars=1000)
    if st.button("Submit for approval", type="primary", width="stretch", disabled=not cart):
        try:
            with session_scope() as session:
                order = order_service.place_order(
                    session, sales_person_id=user.id, customer_id=selected.id, lines=lines,
                    notes=notes, advance_payment_pct=advance_payment_pct,
                )
                order_id, order_no = order.id, order.order_no
        except order_service.OrderError as exc:
            st.error(str(exc))
        else:
            with st.spinner("Notifying administrators..."):
                result = emails.send_admin_new_order_alert(order_id)
            msg = f"Order {order_no} submitted and sent for approval."
            if not result.ok:
                msg += " (Admin email could not be sent; admins will still see it in the app.)"
            for pid in cart:
                st.session_state.pop(f"cart_{pid}", None)
            cart.clear()
            st.session_state.pop("order_customer_id", None)
            st.session_state["order_flash"] = msg
            st.rerun()
    if cart and st.button("Clear cart", width="stretch"):
        for pid in cart:
            st.session_state.pop(f"cart_{pid}", None)
        cart.clear()
        st.rerun()
