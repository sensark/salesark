import pandas as pd
import streamlit as st

from erp.auth import require_role
from erp.db import session_scope
from erp.models import REGIONS, ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER
from erp.services import customers as customer_service
from erp.ui.customer_form import customer_fields
from erp.ui.components import page_header, section

user = require_role(ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER)
page_header("Customers", "Find existing customers or register a new one.", "Sales Workspace")

left, right = st.columns([2, 1], gap="large")

with left:
    section("Customer directory")
    term = st.text_input("Search", placeholder="Name, company, email or phone")
    with session_scope() as session:
        rows = [
            {
                "Name": c.name, "Company": c.company or "", "Email": c.email, "Phone": c.phone or "",
                "Region": c.region, "City": c.city or "", "Status": c.customer_status,
                "Credit limit": float(c.credit_limit), "Orders": len(c.orders), "_id": c.id,
            }
            for c in customer_service.search(session, term, limit=500)
        ]
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No customers found.")
    else:
        f1, f2, f3 = st.columns(3, vertical_alignment="bottom")
        customer_region = f1.selectbox("Region", ["All", *sorted(df["Region"].unique())])
        customer_status = f2.selectbox("Customer status", ["All", *sorted(df["Status"].unique())])
        customer_sort = f3.selectbox("Sort customers", ["Name", "Most orders", "Highest credit"])
        df = df[(customer_region == "All") | (df["Region"] == customer_region)]
        df = df[(customer_status == "All") | (df["Status"] == customer_status)]
        sort_column = {"Name": "Name", "Most orders": "Orders", "Highest credit": "Credit limit"}[customer_sort]
        df = df.sort_values(sort_column, ascending=customer_sort == "Name")
        event = st.dataframe(
            df.drop(columns="_id"), hide_index=True, height=460,
            on_select="rerun", selection_mode="single-row",
        )
        picked = event.selection.rows
        if picked:
            row = df.iloc[picked[0]]
            c1, c2 = st.columns(2)
            if c1.button(f"Start order for {row['Name']}", type="primary"):
                st.session_state["order_customer_id"] = int(row["_id"])
                st.session_state["cart"] = {}
                st.switch_page("views/sales_new_order.py")
            if user.role in {ROLE_ADMIN, ROLE_SALES_MANAGER}:
                new_status = "INACTIVE" if row["Status"] == "ACTIVE" else "ACTIVE"
                if c2.button(f"Set {new_status.lower()}", key=f"customer_status_{row['_id']}"):
                    try:
                        with session_scope() as session:
                            customer_service.set_status(
                                session, customer_id=int(row["_id"]), actor_id=user.id,
                                status=new_status,
                            )
                        st.success(f"Customer status changed to {new_status.lower()}.")
                        st.rerun()
                    except customer_service.CustomerError as exc:
                        st.error(str(exc))

with right:
    section("Add customer")
    with st.form("add_customer", clear_on_submit=True, border=True):
        name = st.text_input("Full name *")
        email = st.text_input("Email *")
        company = st.text_input("Company")
        phone = st.text_input("Phone")
        region = st.selectbox("Region *", REGIONS)
        city = st.text_input("City")
        address = st.text_area("Address", height=70)
        extra_fields = customer_fields("directory_customer")
        if st.form_submit_button("Save customer", type="primary", width="stretch"):
            try:
                with session_scope() as session:
                    customer_service.create(
                        session, name=name, email=email, region=region, created_by_id=user.id,
                        company=company, phone=phone, city=city, address=address,
                        **extra_fields,
                    )
                st.success(f"Customer {name.strip()} saved.")
            except customer_service.CustomerError as exc:
                st.error(str(exc))
