from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from erp.auth import require_role
from erp.db import session_scope
from erp.models import ROLE_ACCOUNTS, ROLE_ADMIN, ROLE_SALES_MANAGER
from erp.permissions import require_action
from erp.services import reports
from erp.ui.components import compact_currency, kpi_row, page_header
from erp.ui.theme import GREEN, NAVY, ORANGE, RED

user = require_role(ROLE_ADMIN, ROLE_SALES_MANAGER, ROLE_ACCOUNTS)

page_header("Sales and Finance Reports", "Analyze sales, fulfillment, tax, collections and returns.", "Reports")

@st.cache_data(ttl=60)
def load_frames():
    with session_scope() as session:
        return (
            reports.sales_lines(session), reports.invoice_lines(session),
            reports.delivery_lines(session), reports.return_lines(session),
            reports.collection_lines(session),
        )

sales_df, invoice_df, delivery_df, return_df, collections_df = load_frames()
dates = []
for frame, column in ((sales_df, "created_at"), (invoice_df, "invoice_date"),
                      (delivery_df, "confirmed_at"), (return_df, "created_at"),
                      (collections_df, "payment_date")):
    if not frame.empty:
        dates.extend(pd.to_datetime(frame[column].dropna()).dt.date.tolist())
if not dates:
    st.info("No transaction data is available yet.")
    st.stop()

start_default, end_default = min(dates), max(dates)
if user.role in {ROLE_ADMIN, ROLE_SALES_MANAGER}:
    filter_col, region_col = st.columns([2, 1])
    selected_range = filter_col.date_input("Date range", (max(start_default, end_default - timedelta(days=365)), end_default))
    all_regions = sorted(set().union(*[
        set(frame["region"].dropna().unique()) for frame in
        (sales_df, invoice_df, delivery_df, return_df, collections_df) if not frame.empty and "region" in frame
    ]))
    regions = region_col.multiselect("Region", all_regions, placeholder="All regions")
else:
    selected_range = st.date_input("Date range", (max(start_default, end_default - timedelta(days=365)), end_default))
    regions = []
start, end = selected_range if isinstance(selected_range, tuple) else (start_default, end_default)

sales = reports.filter_dates(sales_df, "created_at", start, end, regions)
invoices = reports.filter_dates(invoice_df, "invoice_date", start, end, regions)
deliveries = reports.filter_dates(delivery_df, "confirmed_at", start, end, regions)
returns_df = reports.filter_dates(return_df, "created_at", start, end, regions)
collections = reports.filter_dates(collections_df, "payment_date", start, end, regions)

if user.role in {ROLE_ADMIN, ROLE_SALES_MANAGER}:
    tabs = st.tabs(["Sales", "Fulfillment", "Tax", "Collections", "Returns"])
    with tabs[0]:
        revenue = float(sales["line_total"].sum()) if not sales.empty else 0.0
        orders_count = int(sales["order_no"].nunique()) if not sales.empty else 0
        kpi_row([
            ("Approved revenue", compact_currency(revenue), f"{orders_count} orders"),
            ("Units sold", f"{int(sales['qty'].sum()):,}" if not sales.empty else "0", "Approved orders", "navy"),
            ("Discount", compact_currency(float((sales["unit_price"] * sales["qty"] - sales["taxable_amount"]).sum())) if not sales.empty else "₹0", "Pre-tax", "amber"),
        ])
        if not sales.empty:
            c1, c2 = st.columns(2)
            daily = sales.groupby(sales["created_at"].dt.date)["line_total"].sum().reset_index(name="revenue")
            with c1:
                fig = px.line(daily, x="created_at", y="revenue", title="Revenue by date")
                fig.update_traces(line_color=ORANGE)
                fig.update_layout(yaxis_tickprefix="₹", xaxis_title=None, yaxis_title=None)
                st.plotly_chart(fig)
            with c2:
                group = sales.groupby("sales_person")["line_total"].sum().sort_values().reset_index()
                fig = px.bar(group, x="line_total", y="sales_person", orientation="h", title="Sales by salesperson")
                fig.update_traces(marker_color=NAVY)
                fig.update_layout(xaxis_tickprefix="₹", yaxis_title=None, xaxis_title=None)
                st.plotly_chart(fig)
            c3, c4 = st.columns(2)
            with c3:
                group = sales.groupby("customer")["line_total"].sum().nlargest(10).sort_values().reset_index()
                fig = px.bar(group, x="line_total", y="customer", orientation="h", title="Top customers")
                fig.update_traces(marker_color=GREEN)
                fig.update_layout(xaxis_tickprefix="₹", yaxis_title=None, xaxis_title=None)
                st.plotly_chart(fig)
            with c4:
                group = sales.groupby("category")["line_total"].sum().sort_values().reset_index()
                fig = px.bar(group, x="category", y="line_total", title="Sales by product category")
                fig.update_traces(marker_color=ORANGE)
                fig.update_layout(yaxis_tickprefix="₹", xaxis_title=None, yaxis_title=None)
                st.plotly_chart(fig)
            st.dataframe(sales, hide_index=True, height=420)
            st.download_button("Download sales lines", sales.to_csv(index=False), "sales-lines.csv", "text/csv")
    with tabs[1]:
        if not sales.empty:
            order_states = sales[["order_no", "customer", "sales_person", "fulfillment_status"]].drop_duplicates()
            order_states = order_states.groupby("fulfillment_status").size().reset_index(name="orders")
            st.dataframe(order_states, hide_index=True)
        if not deliveries.empty:
            st.dataframe(deliveries, hide_index=True, height=420)
            warehouse = deliveries.groupby(["warehouse", "delivery_status"])["qty"].sum().reset_index()
            fig = px.bar(warehouse, x="warehouse", y="qty", color="delivery_status", title="Units dispatched by warehouse")
            fig.update_layout(yaxis_title="Units")
            st.plotly_chart(fig)
        else:
            st.info("No delivery records exist for this period.")
        st.caption("Order fulfillment states are visible from Sales Orders; confirmed delivery quantities are listed above.")
    with tabs[2]:
        if invoices.empty:
            st.info("No issued invoices for this period.")
        else:
            tax = invoices.groupby("gst_rate").agg(
                taxable=("taxable_amount", "sum"), cgst=("cgst_amount", "sum"),
                sgst=("sgst_amount", "sum"), igst=("igst_amount", "sum"), cess=("cess_amount", "sum"),
            ).reset_index()
            st.dataframe(tax, hide_index=True, column_config={
                column: st.column_config.NumberColumn(format="₹%.2f")
                for column in ("taxable", "cgst", "sgst", "igst", "cess")
            })
            tax_by_hsn = invoices.groupby("hsn_sac", dropna=False)[
                ["taxable_amount", "cgst_amount", "sgst_amount", "igst_amount", "cess_amount"]
            ].sum().reset_index()
            st.dataframe(tax_by_hsn, hide_index=True)
            st.download_button("Download GST report", tax_by_hsn.to_csv(index=False), "gst-report.csv", "text/csv")
    with tabs[3]:
        if collections.empty:
            st.info("No allocated receipts exist for this period.")
        else:
            kpi_row([
                ("Collections", compact_currency(float(collections["allocated_amount"].sum())),
                 f"{collections['receipt_no'].nunique()} receipts"),
                ("Customers", str(collections["customer"].nunique()), "With allocated receipts", "navy"),
            ])
            by_person = collections.groupby("sales_person")["allocated_amount"].sum().sort_values(ascending=False).reset_index()
            st.dataframe(by_person, hide_index=True, column_config={
                "allocated_amount": st.column_config.NumberColumn("Collection", format="₹%.2f")
            })
            st.dataframe(collections, hide_index=True)
            st.download_button("Download collections", collections.to_csv(index=False), "collections.csv", "text/csv")
    with tabs[4]:
        if returns_df.empty:
            st.info("No return records exist for this period.")
        else:
            by_reason = returns_df.groupby("reason")["qty"].sum().sort_values(ascending=False).reset_index()
            c1, c2 = st.columns(2)
            with c1:
                fig = px.bar(by_reason, x="reason", y="qty", title="Returned units by reason")
                fig.update_traces(marker_color=RED)
                st.plotly_chart(fig)
            with c2:
                by_product = returns_df.groupby("product")["qty"].sum().nlargest(10).reset_index()
                fig = px.bar(by_product, x="qty", y="product", orientation="h", title="Returns by product")
                fig.update_traces(marker_color=ORANGE)
                st.plotly_chart(fig)
            st.dataframe(returns_df, hide_index=True)
            st.download_button("Download returns", returns_df.to_csv(index=False), "sales-returns.csv", "text/csv")
else:
    if user.role == ROLE_ACCOUNTS:
        require_action(user.role, "report.financial.read")
    if not invoices.empty:
        st.subheader("Invoices by tax rate and HSN/SAC")
        st.dataframe(invoices, hide_index=True)
    if not collections.empty:
        st.subheader("Collections")
        st.dataframe(collections, hide_index=True)
    if not returns_df.empty:
        st.subheader("Returns and credits")
        st.dataframe(returns_df, hide_index=True)
