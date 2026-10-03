from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from erp.auth import require_role
from erp.db import session_scope
from erp.models import ROLE_ADMIN, ROLE_SALES_MANAGER
from erp.services import analytics as an
from erp.ui.components import compact_currency, kpi_row, page_header, section
from erp.ui.theme import GREEN, NAVY, NAVY_3, ORANGE, RED, AMBER

require_role(ROLE_ADMIN, ROLE_SALES_MANAGER)
page_header("Sales Analytics", "Revenue, team performance, products, customers and discount impact.", "Administration")


@st.cache_data(ttl=60, show_spinner="Loading data...")
def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    with session_scope() as session:
        return an.orders_frame(session), an.items_frame(session)


orders_all, items_all = load()
if orders_all.empty:
    st.info("No orders yet. Run `python scripts/seed_data.py` to generate test data.")
    st.stop()

min_d, max_d = orders_all["created_at"].min().date(), orders_all["created_at"].max().date()
with st.container(border=True):
    f1, f2, f3, f4 = st.columns(
        [1.3, 1.3, 1.3, 0.6], vertical_alignment="bottom"
    )
    period = f1.date_input("Date range", (max(min_d, max_d - timedelta(days=365)), max_d),
                           min_value=min_d, max_value=max(max_d, date.today()))
    regions = f2.multiselect("Region", sorted(orders_all["region"].unique()), placeholder="All regions")
    people = f3.multiselect("Sales person", sorted(orders_all["sales_person"].unique()), placeholder="All")
    f4.write("")
    if f4.button("Refresh", width="stretch"):
        load.clear()
        st.rerun()

start, end = (period if isinstance(period, tuple) and len(period) == 2 else (min_d, max_d))
orders = an.filter_orders(orders_all, start, end, regions, people)
approved = orders[orders["status"] == "APPROVED"]
items = an.approved_items(approved, items_all)

# Comparison against the preceding period of equal length.
span = (end - start) + timedelta(days=1)
prev = an.filter_orders(orders_all, start - span, start - timedelta(days=1), regions, people)
k, kp = an.kpis(orders), an.kpis(prev)


def delta(cur: float, old: float) -> str:
    if not old:
        return "No prior period data"
    return f"{(cur - old) / old * 100:+.1f}% vs prior period"


kpi_row([
    ("Revenue", compact_currency(k["revenue"]), delta(k["revenue"], kp["revenue"])),
    ("Approved orders", f"{k['orders']:,}", delta(k["orders"], kp["orders"]), "navy"),
    ("Avg order value", compact_currency(k["avg_order"]), delta(k["avg_order"], kp["avg_order"]), "green"),
    ("Discount given", compact_currency(k["discount"]),
     f"{k['discount'] / (k['revenue'] + k['discount']) * 100:.1f}% of gross" if k["revenue"] else "", "amber"),
    ("Approval rate", f"{k['approval_rate'] * 100:.0f}%", f"{k['pending']} pending", "navy"),
])
st.write("")

tab_rev, tab_team, tab_prod, tab_cust, tab_disc = st.tabs(
    ["Revenue", "Sales Team", "Products", "Customers and Regions", "Discounts and Approvals"]
)

with tab_rev:
    monthly = an.monthly_revenue(approved)
    fig = go.Figure()
    fig.add_bar(x=monthly["month"], y=monthly["revenue"], name="Revenue", marker_color=NAVY_3)
    fig.add_scatter(x=monthly["month"], y=monthly["revenue"].rolling(3, min_periods=1).mean(),
                    name="3-month average", line=dict(color=ORANGE, width=3), mode="lines+markers")
    fig.update_layout(title="Monthly revenue", height=420, legend=dict(orientation="h", y=1.1),
                      yaxis_tickprefix="₹", yaxis_tickformat=",.0f")
    st.plotly_chart(fig)
    c1, c2 = st.columns(2)
    with c1:
        fig = px.area(monthly, x="month", y="orders", title="Approved orders per month")
        fig.update_traces(line_color=ORANGE, fillcolor="rgba(255,122,0,.18)")
        st.plotly_chart(fig)
    with c2:
        if not approved.empty:
            dow = approved.assign(day=approved["created_at"].dt.day_name())
            order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            dow = dow.groupby("day")["total"].sum().reindex(order).reset_index()
            fig = px.bar(dow, x="day", y="total", title="Revenue by weekday")
            fig.update_traces(marker_color=NAVY)
            fig.update_layout(yaxis_tickprefix="₹", xaxis_title=None, yaxis_title=None)
            st.plotly_chart(fig)

with tab_team:
    board = an.leaderboard(orders)
    if board.empty:
        st.info("No data for the selected filters.")
    else:
        c1, c2 = st.columns([1.3, 1])
        with c1:
            fig = px.bar(board.sort_values("revenue"), x="revenue", y="sales_person", orientation="h",
                         title="Revenue by sales person", text=board.sort_values("revenue")["revenue"].map(compact_currency))
            fig.update_traces(marker_color=ORANGE, textposition="outside")
            fig.update_layout(height=380, xaxis_tickprefix="₹", yaxis_title=None, xaxis_title=None)
            st.plotly_chart(fig)
        with c2:
            fig = px.scatter(board, x="approved_orders", y="avg_order", size="revenue", color="sales_person",
                             title="Volume vs average order value", size_max=48)
            fig.update_layout(height=380, yaxis_tickprefix="₹", showlegend=False)
            st.plotly_chart(fig)
        trend = approved.assign(month=approved["created_at"].dt.to_period("M").dt.to_timestamp()) \
            .groupby(["month", "sales_person"])["total"].sum().reset_index()
        fig = px.line(trend, x="month", y="total", color="sales_person", markers=True,
                      title="Monthly revenue by sales person")
        fig.update_layout(height=380, yaxis_tickprefix="₹", legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig)
        section("Leaderboard")
        st.dataframe(
            board, hide_index=True,
            column_config={
                "sales_person": "Sales person",
                "revenue": st.column_config.ProgressColumn("Revenue", format="₹%.0f", min_value=0,
                                                           max_value=float(board["revenue"].max() or 1)),
                "approved_orders": "Approved", "rejected_orders": "Rejected", "pending_orders": "Pending",
                "customers": "Customers",
                "discount_given": st.column_config.NumberColumn("Discount given", format="₹%.0f"),
                "approval_rate": st.column_config.NumberColumn("Approval rate", format="percent"),
                "avg_order": st.column_config.NumberColumn("Avg order", format="₹%.0f"),
            },
        )

with tab_prod:
    if items.empty:
        st.info("No data for the selected filters.")
    else:
        c1, c2 = st.columns([1.4, 1])
        with c1:
            top = an.top_products(items, 12)
            fig = px.bar(top.sort_values("revenue"), x="revenue", y="product", color="category",
                         orientation="h", title="Top products by revenue")
            fig.update_layout(height=460, xaxis_tickprefix="₹", yaxis_title=None, legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig)
        with c2:
            cat = an.category_revenue(items)
            fig = px.pie(cat, names="category", values="revenue", hole=0.55, title="Revenue share by category")
            fig.update_traces(textinfo="percent+label")
            fig.update_layout(height=460, showlegend=False)
            st.plotly_chart(fig)
        cat_month = items.assign(month=items["created_at"].dt.to_period("M").dt.to_timestamp()) \
            .groupby(["month", "category"])["line_total"].sum().reset_index()
        fig = px.area(cat_month, x="month", y="line_total", color="category", title="Category revenue over time")
        fig.update_layout(height=380, yaxis_tickprefix="₹", yaxis_title=None, legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig)
        pareto_products = an.pareto_products(items)
        cutoff = int((pareto_products["cumulative_revenue_share"] < 0.8).sum()) + 1
        st.metric("Products generating the first 80% of revenue", f"{cutoff} / {len(pareto_products)}")
        pareto_products["rank"] = range(1, len(pareto_products) + 1)
        fig = go.Figure()
        fig.add_bar(x=pareto_products["rank"], y=pareto_products["revenue"], name="Revenue",
                marker_color=ORANGE)
        fig.add_scatter(x=pareto_products["rank"], y=pareto_products["cumulative_revenue_share"] * 100,
                name="Cumulative revenue", yaxis="y2", mode="lines+markers",
                line=dict(color=NAVY, width=3))
        fig.add_hline(y=80, yref="y2", line_dash="dash", line_color=GREEN)
        fig.update_layout(title="Product Pareto analysis", height=420, xaxis_title="Product rank",
                  yaxis=dict(title="Revenue (INR)", tickprefix="₹"),
                  yaxis2=dict(title="Cumulative revenue (%)", overlaying="y", side="right",
                          range=[0, 105]))
        st.plotly_chart(fig)

with tab_cust:
    if approved.empty:
        st.info("No data for the selected filters.")
    else:
        c1, c2 = st.columns([1.3, 1])
        with c1:
            tc = an.top_customers(approved, 10)
            tc["label"] = tc["customer"] + " (" + tc["company"].fillna("Individual") + ")"
            fig = px.bar(tc.sort_values("revenue"), x="revenue", y="label", orientation="h",
                         color="region", title="Top 10 customers")
            fig.update_layout(height=440, xaxis_tickprefix="₹", yaxis_title=None, legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig)
        with c2:
            reg = an.region_revenue(approved)
            fig = px.bar(reg, x="region", y="revenue", title="Revenue by region",
                         text=reg["revenue"].map(compact_currency))
            fig.update_traces(marker_color=[ORANGE, NAVY_3, NAVY, AMBER, GREEN][: len(reg)], textposition="outside")
            fig.update_layout(height=440, yaxis_tickprefix="₹", xaxis_title=None)
            st.plotly_chart(fig)
        if not items.empty:
            heat = items.pivot_table(index="region", columns="category", values="line_total", aggfunc="sum", fill_value=0)
            fig = px.imshow(heat, text_auto=".2s", aspect="auto", title="Region x category revenue",
                            color_continuous_scale=["#FFFFFF", "#FFD2A8", ORANGE, NAVY])
            fig.update_layout(height=380)
            st.plotly_chart(fig)
        section("Regional summary")
        st.dataframe(an.region_revenue(approved), hide_index=True,
                     column_config={"revenue": st.column_config.NumberColumn("Revenue", format="₹%.0f")})
        pareto_customers = an.pareto_customers(approved)
        cutoff = int((pareto_customers["cumulative_revenue_share"] < 0.8).sum()) + 1
        st.metric("Customers generating the first 80% of revenue",
              f"{cutoff} / {len(pareto_customers)}")
        pareto_customers["rank"] = range(1, len(pareto_customers) + 1)
        fig = go.Figure()
        fig.add_bar(x=pareto_customers["rank"], y=pareto_customers["revenue"],
                name="Revenue", marker_color=ORANGE)
        fig.add_scatter(
            x=pareto_customers["rank"],
            y=pareto_customers["cumulative_revenue_share"] * 100,
            name="Cumulative revenue", yaxis="y2", mode="lines+markers",
            line=dict(color=NAVY, width=3),
        )
        fig.add_hline(y=80, yref="y2", line_dash="dash", line_color=GREEN)
        fig.update_layout(
            title="Customer Pareto analysis", height=420,
            xaxis_title="Customer rank",
            yaxis=dict(title="Revenue (INR)", tickprefix="₹"),
            yaxis2=dict(title="Cumulative revenue (%)", overlaying="y", side="right",
                range=[0, 105]),
        )
        st.plotly_chart(fig)

with tab_disc:
    c1, c2 = st.columns(2)
    with c1:
        bands = an.discount_bands(items)
        if not bands.empty:
            fig = go.Figure()
            fig.add_bar(x=bands["band"], y=bands["revenue"], name="Net revenue", marker_color=NAVY_3)
            fig.add_bar(x=bands["band"], y=bands["discount"], name="Discount given", marker_color=ORANGE)
            fig.update_layout(barmode="stack", title="Revenue and discount by discount tier", height=400,
                              yaxis_tickprefix="₹", legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig)
    with c2:
        if not bands.empty:
            fig = px.bar(bands, x="band", y="avg_units", title="Average units per line by discount tier",
                         text=bands["avg_units"].round(1))
            fig.update_traces(marker_color=GREEN, textposition="outside")
            fig.update_layout(height=400, xaxis_title=None, yaxis_title="Units")
            st.plotly_chart(fig)
    c3, c4 = st.columns(2)
    with c3:
        fn = an.funnel(orders)
        fig = go.Figure(go.Funnel(y=fn["stage"], x=fn["count"], textinfo="value+percent initial",
                                  marker=dict(color=[NAVY_3, AMBER, GREEN])))
        fig.update_layout(title="Approval funnel", height=380)
        st.plotly_chart(fig)
    with c4:
        status_counts = orders["status"].value_counts().reset_index()
        fig = px.pie(status_counts, names="status", values="count", hole=0.55, title="Order status mix",
                     color="status", color_discrete_map={"APPROVED": GREEN, "PENDING": AMBER, "REJECTED": RED})
        fig.update_layout(height=380)
        st.plotly_chart(fig)
    hours = an.approval_hours(orders)
    if not hours.empty:
        st.markdown(
            f'<div class="hint">Average time to decision: <b>{hours.mean():.1f} hours</b> '
            f'&middot; median {hours.median():.1f} hours &middot; 90th percentile {hours.quantile(.9):.1f} hours</div>',
            unsafe_allow_html=True,
        )
        fig = px.histogram(hours, nbins=30, title="Time to decision (hours)")
        fig.update_traces(marker_color=NAVY_3)
        fig.update_layout(height=320, showlegend=False, xaxis_title="Hours", yaxis_title="Orders")
        st.plotly_chart(fig)
