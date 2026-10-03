import streamlit as st
from sqlalchemy import select

from erp.auth import require_role
from erp.db import session_scope
from erp.models import InventoryMovement, Product, ROLE_ADMIN, ROLE_WAREHOUSE, Warehouse
from erp.permissions import require_action
from erp.services import inventory, predictions
from erp.ui.components import page_header, section

user = require_role(ROLE_ADMIN, ROLE_WAREHOUSE)
page_header("Stock Movements", "Review the inventory ledger and record controlled adjustments.", "Warehouse")

section("Current stock")
with session_scope() as session:
    products = list(session.scalars(select(Product).order_by(Product.category, Product.name)))
    movements = list(session.scalars(
        select(InventoryMovement).order_by(InventoryMovement.occurred_at.desc()).limit(500)
    ))
    product_names = {p.id: p.name for p in products}
    warehouse_names = {
        w.id: w.name for w in session.scalars(select(Warehouse))
    }
    plan = predictions.reorder_frame(session)

plan = plan.set_index("product_id") if not plan.empty else plan


def _plan(pid: int, column: str):
    return plan.at[pid, column] if not plan.empty and pid in plan.index else None


f1, f2, f3, f4 = st.columns(
    [1.2, 1, 1, 1.4], vertical_alignment="bottom"
)
stock_search = f1.text_input("Search stock", placeholder="SKU or product")
stock_category = f2.selectbox("Stock category", ["All", *sorted({p.category for p in products})])
stock_filter = f3.selectbox("Stock status", ["All", "Low stock", "In stock"])
stock_sort = f4.selectbox(
    "Sort stock", ["Category and name", "Lowest stock", "Highest stock"]
)
visible_products = [
    product for product in products
    if (not stock_search.strip() or stock_search.casefold() in product.sku.casefold()
        or stock_search.casefold() in product.name.casefold())
    and (stock_category == "All" or product.category == stock_category)
    and (stock_filter == "All"
         or product.is_low_stock == (stock_filter == "Low stock"))
]
visible_products.sort(key={
    "Category and name": lambda product: (product.category, product.name.casefold()),
    "Lowest stock": lambda product: product.stock,
    "Highest stock": lambda product: -product.stock,
}[stock_sort])
st.dataframe(
    [{"SKU": p.sku, "Product": p.name, "Category": p.category, "On hand": p.stock,
      "Reorder at": p.reorder_level, "Status": "LOW" if p.is_low_stock else "OK",
      "Forecast / week": _plan(p.id, "weekly_demand"), "Days of cover": _plan(p.id, "days_of_cover"),
      "Forecast reorder point": _plan(p.id, "reorder_point"), "Suggested order": _plan(p.id, "suggested_qty")}
    for p in visible_products],
    hide_index=True,
    column_config={
        "Forecast / week": st.column_config.NumberColumn(format="%.1f"),
        "Days of cover": st.column_config.NumberColumn(format="%.0f"),
    },
)
if not plan.empty:
    st.caption(f"Forecasts refreshed {plan['scored_at'].max():%d %b %Y %H:%M}. Suggested order covers the "
               "supplier lead time plus four weeks of forecast demand with safety stock.")

section("Record stock adjustment")
with st.form("stock_adjustment", border=True):
    product = st.selectbox("Product", products, format_func=lambda p: f"{p.sku} · {p.name}")
    delta = st.number_input("Quantity change (+ receive / - remove)", min_value=-100000, max_value=100000, value=0)
    reason = st.text_input("Reason")
    if st.form_submit_button("Post adjustment", type="primary"):
        try:
            require_action(user.role, "inventory.adjust")
            if not delta or not reason.strip():
                raise ValueError("Enter a nonzero quantity and a reason.")
            with session_scope() as session:
                inventory.record_movement(
                    session, product_id=product.id, qty_delta=int(delta),
                    source_type="STOCK_ADJUSTMENT", source_id=product.id,
                    source_line_id=None, actor_id=user.id, reason=reason.strip(),
                )
            st.success(f"Stock adjustment posted for {product.name}.")
            st.rerun()
        except (PermissionError, ValueError) as exc:
            st.error(str(exc))

section("Movement history")
movement_search = st.text_input("Search movements", placeholder="Product, source, or reason")
movement_sources = sorted({movement.source_type for movement in movements})
movement_source = st.selectbox("Movement source", ["All", *movement_sources])
movement_sort = st.selectbox("Sort movements", ["Newest", "Oldest"])
visible_movements = [
    movement for movement in movements
    if (movement_source == "All" or movement.source_type == movement_source)
    and (not movement_search.strip()
         or movement_search.casefold() in product_names.get(movement.product_id, "").casefold()
         or movement_search.casefold() in movement.source_type.casefold()
         or movement_search.casefold() in (movement.reason or "").casefold())
]
visible_movements.sort(key=lambda movement: movement.occurred_at,
                       reverse=movement_sort == "Newest")
st.dataframe(
    [{"When": m.occurred_at, "Product": product_names.get(m.product_id, ""),
      "Warehouse": warehouse_names.get(m.warehouse_id, ""), "Change": m.qty_delta,
      "Source": m.source_type, "Reference": m.source_id, "Reason": m.reason or ""}
    for m in visible_movements],
    hide_index=True, height=480,
    column_config={"When": st.column_config.DatetimeColumn(format="DD MMM YYYY HH:mm")},
)
