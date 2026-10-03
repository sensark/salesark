from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import select

from erp.auth import require_role
from erp.db import session_scope
from erp.models import Customer, CustomerProductPrice, PriceList, PriceListItem, Product, QuantityPriceTier, ROLE_ADMIN
from erp.services import products
from erp.services.products import ProductError
from erp.ui.components import page_header, section

admin = require_role(ROLE_ADMIN)
page_header("Pricing Rules", "Manage dealer price lists, customer agreements and quantity price breaks.", "Administration")

if message := st.session_state.pop("pricing_flash", None):
    st.success(message)

with session_scope() as session:
    price_lists = list(session.scalars(select(PriceList).where(PriceList.active.is_(True)).order_by(PriceList.name)))
    customer_list = list(session.scalars(select(Customer).where(Customer.customer_status == "ACTIVE").order_by(Customer.name)))
    product_list = list(session.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.name)))
    list_rows = list(session.scalars(select(PriceListItem)))
    customer_rows = list(session.scalars(select(CustomerProductPrice)))

list_tab, customer_tab, quantity_tab = st.tabs(["Price lists", "Customer prices", "Quantity pricing"])
with list_tab:
    section("Price-list price")
    if not price_lists or not product_list:
        st.info("Create an active price list and product first.")
    else:
        with st.form("price_list_price", border=True):
            price_list = st.selectbox("Price list", price_lists, format_func=lambda row: f"{row.name} · {row.currency}")
            product = st.selectbox("Product", product_list, format_func=lambda row: f"{row.sku} · {row.name}")
            current = next((row for row in list_rows
                            if row.price_list_id == price_list.id and row.product_id == product.id), None)
            price = st.number_input("Unit price", min_value=0.01, step=100.0,
                                    value=float(current.unit_price) if current else float(product.unit_price))
            if st.form_submit_button("Save price", type="primary"):
                try:
                    with session_scope() as session:
                        products.save_price_list_item(
                            session, actor_id=admin.id, price_list_id=price_list.id,
                            product_id=product.id, unit_price=Decimal(str(price)),
                        )
                    st.session_state["pricing_flash"] = f"{product.sku} saved to {price_list.name}."
                    st.rerun()
                except ProductError as exc:
                    st.error(str(exc))
    st.dataframe(
        [{"Price list": row.price_list_id, "Product": row.product_id,
          "Unit price": float(row.unit_price)} for row in list_rows],
        hide_index=True, column_config={"Unit price": st.column_config.NumberColumn(format="₹%.2f")},
    )

with customer_tab:
    section("Customer-specific price")
    if not customer_list or not product_list:
        st.info("Add active customers and products first.")
    else:
        with st.form("customer_price", border=True):
            customer = st.selectbox("Customer", customer_list, format_func=lambda row: f"{row.name} · {row.email}")
            product = st.selectbox("Product", product_list, format_func=lambda row: f"{row.sku} · {row.name}", key="customer_price_product")
            current = next((row for row in customer_rows
                            if row.customer_id == customer.id and row.product_id == product.id), None)
            price = st.number_input("Agreed unit price", min_value=0.01, step=100.0,
                                    value=float(current.unit_price) if current else float(product.unit_price))
            active = st.checkbox("Active", value=current.active if current else True)
            if st.form_submit_button("Save customer price", type="primary"):
                try:
                    with session_scope() as session:
                        products.save_customer_price(
                            session, actor_id=admin.id, customer_id=customer.id,
                            product_id=product.id, unit_price=Decimal(str(price)), active=active,
                        )
                    st.session_state["pricing_flash"] = f"Customer price saved for {customer.name}."
                    st.rerun()
                except ProductError as exc:
                    st.error(str(exc))
    st.dataframe(
        [{"Customer": row.customer_id, "Product": row.product_id,
          "Unit price": float(row.unit_price), "Active": row.active} for row in customer_rows],
        hide_index=True, column_config={"Unit price": st.column_config.NumberColumn(format="₹%.2f")},
    )

with quantity_tab:
    section("Quantity price breaks")
    if not product_list:
        st.info("Create products first.")
    else:
        product = st.selectbox("Product", product_list, format_func=lambda row: f"{row.sku} · {row.name}", key="quantity_price_product")
        with session_scope() as session:
            current_tiers = list(session.scalars(
                select(QuantityPriceTier).where(QuantityPriceTier.product_id == product.id)
                .order_by(QuantityPriceTier.min_qty)
            ))
        frame = pd.DataFrame(
            [{"Minimum qty": tier.min_qty, "Unit price": float(tier.unit_price)} for tier in current_tiers],
            columns=["Minimum qty", "Unit price"],
        )
        edited = st.data_editor(
            frame, num_rows="dynamic", key=f"quantity_prices_{product.id}",
            column_config={
                "Minimum qty": st.column_config.NumberColumn(min_value=1, step=1, required=True),
                "Unit price": st.column_config.NumberColumn(min_value=0.01, step=100.0, required=True,
                                                               format="₹%.2f"),
            },
        )
        if st.button("Save quantity prices", type="primary"):
            rows = edited.dropna()
            try:
                with session_scope() as session:
                    products.replace_quantity_prices(
                        session, actor_id=admin.id, product_id=product.id,
                        tiers=[(int(row["Minimum qty"]), Decimal(str(row["Unit price"])))
                               for _, row in rows.iterrows()],
                    )
                st.session_state["pricing_flash"] = f"Quantity prices saved for {product.name}."
                st.rerun()
            except ProductError as exc:
                st.error(str(exc))
