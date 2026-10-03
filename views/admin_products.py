from decimal import Decimal

import pandas as pd
import streamlit as st

from erp.auth import require_role
from erp.db import session_scope
from erp.models import ROLE_ADMIN
from erp.services import products as product_service
from erp.ui.components import hint, kpi_row, page_header, section

user = require_role(ROLE_ADMIN)
page_header("Products and Discounts", "Manage catalog, stock levels and volume discount tiers.", "Administration")

if flash := st.session_state.pop("product_flash", None):
    st.success(flash)

with session_scope() as session:
    products = product_service.list_products(session, active_only=False)

low = [p for p in products if p.active and p.is_low_stock]
kpi_row([
    ("Active products", str(sum(p.active for p in products)), f"{len(products)} total"),
    ("Low stock", str(len(low)), "At or below reorder level", "amber"),
    ("Out of stock", str(sum(p.active and p.stock == 0 for p in products)), "Cannot be approved", "navy"),
    ("Categories", str(len({p.category for p in products})), "", "green"),
])

if low:
    hint("Low stock: " + ", ".join(f"{p.name} ({p.stock} left)" for p in low[:12])
         + (" and more" if len(low) > 12 else ""), "warn")

tab_list, tab_edit, tab_tiers = st.tabs(["Catalog", "Add or edit product", "Discount tiers"])

with tab_list:
    f1, f2, f3, f4 = st.columns(
        [1.3, 1, 1, 1], vertical_alignment="bottom"
    )
    product_search = f1.text_input("Search catalog", placeholder="SKU or product")
    categories = sorted({p.category for p in products})
    product_category = f2.selectbox("Category", ["All", *categories])
    product_active = f3.selectbox("Catalog status", ["All", "Active", "Inactive"])
    product_sort = f4.selectbox("Sort products", ["Name", "Price: high to low", "Stock: low to high"])
    visible_products = [p for p in products
                        if (not product_search.strip()
                            or product_search.casefold() in p.sku.casefold()
                            or product_search.casefold() in p.name.casefold())
                        and (product_category == "All" or p.category == product_category)
                        and (product_active == "All"
                             or p.active == (product_active == "Active"))]
    visible_products.sort(key={
        "Name": lambda product: product.name.casefold(),
        "Price: high to low": lambda product: -product.unit_price,
        "Stock: low to high": lambda product: product.stock,
    }[product_sort])
    df = pd.DataFrame([
        {
            "SKU": p.sku, "Name": p.name, "Category": p.category, "Unit price": float(p.unit_price),
            "Unit": p.unit, "HSN/SAC": p.hsn_sac or "", "GST %": float(p.gst_rate),
            "Stock": p.stock, "Reorder level": p.reorder_level,
            "Status": "Low stock" if p.is_low_stock else "OK", "Active": p.active,
            "Tiers": ", ".join(f"{t.min_qty}+ {t.discount_pct:.0f}%" for t in p.tiers) or "None",
        }
        for p in visible_products
    ])

    def _highlight(row):
        return ["background-color: #FFE9D6" if row["Status"] == "Low stock" else ""] * len(row)

    st.dataframe(
        df.style.apply(_highlight, axis=1).format({"Unit price": "₹{:,.2f}"}),
        hide_index=True, height=520,
    )

with tab_edit:
    choice = st.selectbox("Product", [None, *products],
                          format_func=lambda p: "Create a new product" if p is None else f"{p.sku} - {p.name}")
    with st.form("product_form"):
        a, b = st.columns(2)
        sku = a.text_input("SKU *", value=choice.sku if choice else "")
        name = b.text_input("Name *", value=choice.name if choice else "")
        category = a.text_input("Category *", value=choice.category if choice else "")
        price = b.number_input("Unit price *", min_value=0.01, step=1.0,
                               value=float(choice.unit_price) if choice else 10.0, format="%.2f")
        unit = a.text_input("Unit", value=choice.unit if choice else "EA")
        hsn_sac = b.text_input("HSN/SAC", value=choice.hsn_sac or "" if choice else "")
        gst_rate = a.number_input("GST rate %", min_value=0.0, max_value=100.0, step=0.5,
                      value=float(choice.gst_rate) if choice else 0.0)
        cess_rate = b.number_input("Cess rate %", min_value=0.0, max_value=100.0, step=0.5,
                       value=float(choice.cess_rate) if choice else 0.0)
        cost = b.number_input("Cost price (INR)", min_value=0.0, step=1.0,
                      value=float(choice.cost_price or 0) if choice else 0.0)
        stock = a.number_input("Stock", min_value=0, step=1, value=choice.stock if choice else 0)
        reorder = b.number_input("Reorder level", min_value=0, step=1, value=choice.reorder_level if choice else 10)
        active = st.checkbox("Active", value=choice.active if choice else True)
        if st.form_submit_button("Save product", type="primary"):
            try:
                with session_scope() as session:
                    product_service.save_product(
                        session, sku=sku, name=name, category=category,
                        unit_price=Decimal(str(round(price, 2))), stock=int(stock), reorder_level=int(reorder),
                        actor_id=user.id, unit=unit, hsn_sac=hsn_sac,
                        gst_rate=Decimal(str(gst_rate)), cess_rate=Decimal(str(cess_rate)),
                        cost_price=Decimal(str(cost)) if cost else None,
                        active=active, product_id=choice.id if choice else None,
                    )
                st.session_state["product_flash"] = f"Product {sku.strip().upper()} saved."
                st.rerun()
            except product_service.ProductError as exc:
                st.error(str(exc))

with tab_tiers:
    section("Volume discount tiers")
    st.caption("The highest tier whose minimum quantity is reached applies to the order line.")
    target = st.selectbox("Product", products, format_func=lambda p: f"{p.sku} - {p.name}", key="tier_product")
    if target:
        tiers_df = pd.DataFrame(
            [{"Min quantity": t.min_qty, "Discount %": float(t.discount_pct)} for t in target.tiers],
            columns=["Min quantity", "Discount %"],
        )
        edited = st.data_editor(
            tiers_df, num_rows="dynamic", key=f"tiers_{target.id}",
            column_config={
                "Min quantity": st.column_config.NumberColumn(min_value=1, step=1, required=True),
                "Discount %": st.column_config.NumberColumn(min_value=0.5, max_value=99, step=0.5, required=True),
            },
        )
        if st.button("Save tiers", type="primary"):
            rows = edited.dropna()
            try:
                with session_scope() as session:
                    product_service.replace_tiers(
                        session, target.id,
                        [(int(r["Min quantity"]), Decimal(str(r["Discount %"]))) for _, r in rows.iterrows()],
                        actor_id=user.id,
                    )
                st.session_state["product_flash"] = f"Discount tiers for {target.name} saved."
                st.rerun()
            except product_service.ProductError as exc:
                st.error(str(exc))
