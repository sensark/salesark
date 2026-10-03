from datetime import date, datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from erp.auth import require_role
from erp.db import session_scope
from erp.models import (
    ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER, STATUS_APPROVED,
    STATUS_PENDING, Customer, Order, User,
)
from erp.services import predictions
from erp.ui.components import compact_currency, hint, kpi_row, page_header, section
from erp.ui.theme import ORANGE

user = require_role(ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER)
page_header("Sales Dashboard", "Your customer activity, order pipeline and revenue progress.", "Sales Workspace")

month_start = datetime(date.today().year, date.today().month, 1)
with session_scope() as session:
    month_orders = list(session.scalars(
        select(Order).where(
            Order.sales_person_id == user.id,
            Order.created_at >= month_start,
        ).order_by(Order.created_at)
    ))
    recent = list(session.execute(
        select(Order, Customer)
        .join(Customer, Customer.id == Order.customer_id)
        .where(Order.sales_person_id == user.id)
        .order_by(Order.created_at.desc()).limit(8)
    ))
    db_user = session.get(User, user.id)
    monthly_target = float(db_user.monthly_target if db_user else 0)
    at_risk = predictions.retention_actions(session, sales_person_id=user.id, limit=10)

approved = [order for order in month_orders if order.status == STATUS_APPROVED]
revenue = float(sum(order.total for order in approved))
pending = [order for order in month_orders if order.status == STATUS_PENDING]

kpi_row([
    ("Month-to-date revenue", compact_currency(revenue), f"{len(approved)} approved orders"),
    ("Monthly target", compact_currency(monthly_target),
     f"{revenue / monthly_target * 100:.0f}% achieved" if monthly_target else "Target not set", "navy"),
    ("Awaiting approval", str(len(pending)), compact_currency(float(sum(o.total for o in pending))), "amber"),
    ("Average order", compact_currency(revenue / len(approved) if approved else 0), "Approved orders this month", "green"),
])

left, right = st.columns([1.5, 1], gap="large")
with left:
    section("Revenue trend")
    if approved:
        frame = pd.DataFrame([{"Date": order.created_at.date(), "Revenue": float(order.total)} for order in approved])
        frame = frame.groupby("Date", as_index=False)["Revenue"].sum()
        fig = px.area(frame, x="Date", y="Revenue")
        fig.update_traces(line_color=ORANGE, fillcolor="rgba(255,122,0,.18)")
        fig.update_layout(height=330, yaxis_tickprefix="₹", xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig)
    else:
        st.info("Approved revenue will appear here once this month has an approved order.")
with right:
    section("Order status")
    counts = pd.DataFrame([
        {"Status": "Pending", "Orders": len(pending)},
        {"Status": "Approved", "Orders": len(approved)},
        {"Status": "Rejected", "Orders": sum(o.status == "REJECTED" for o in month_orders)},
    ])
    fig = px.bar(counts, x="Orders", y="Status", orientation="h", color="Status",
                 color_discrete_map={"Pending": "#F2B138", "Approved": "#1E9E5A", "Rejected": "#D64545"})
    fig.update_layout(height=260, showlegend=False, xaxis_title=None, yaxis_title=None)
    st.plotly_chart(fig)

section("Recent orders")
if recent:
    f1, f2, f3 = st.columns(3, vertical_alignment="bottom")
    recent_search = f1.text_input(
        "Search recent orders", placeholder="Order number or customer"
    )
    recent_status = f2.selectbox(
        "Recent order status", ["All", *sorted({o.status for o, _ in recent})]
    )
    recent_sort = f3.selectbox(
        "Sort recent orders", ["Newest", "Oldest", "Highest total"]
    )
    visible_recent = [
        (order, customer) for order, customer in recent
        if (recent_status == "All" or order.status == recent_status)
        and (not recent_search.strip() or recent_search.casefold() in order.order_no.casefold()
             or recent_search.casefold() in customer.name.casefold())
    ]
    visible_recent.sort(
        key=lambda row: row[0].total if recent_sort == "Highest total" else row[0].created_at,
        reverse=recent_sort != "Oldest",
    )
    st.dataframe(
        [{"Order": order.order_no, "Customer": customer.name, "Status": order.status,
          "Created": order.created_at, "Total": float(order.total)}
         for order, customer in visible_recent],
        hide_index=True,
        column_config={
            "Created": st.column_config.DatetimeColumn(format="DD MMM YYYY HH:mm"),
            "Total": st.column_config.NumberColumn(format="₹%.2f"),
        },
    )
else:
    st.info("You have not submitted any orders yet.")

section("Customers at risk of churning")
if at_risk.empty:
    hint("No at-risk customers in your book, or predictions have not been generated yet.")
else:
    st.dataframe(
        at_risk[["customer", "company", "phone", "churn_probability", "value_at_risk", "recency_days",
                 "drivers", "action"]],
        hide_index=True,
        column_config={
            "churn_probability": st.column_config.ProgressColumn("Churn risk", format="percent", min_value=0, max_value=1),
            "value_at_risk": st.column_config.NumberColumn("Value at risk", format="₹%.0f"),
            "recency_days": st.column_config.NumberColumn("Days since order"),
            "drivers": st.column_config.TextColumn("Why", width="large"),
            "action": st.column_config.TextColumn("Recommended action", width="large"),
        },
    )
