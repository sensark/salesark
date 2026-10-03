import streamlit as st

from erp.auth import require_role
from erp.db import session_scope
from erp.models import (
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    ROLE_SALES,
    ROLE_SALES_MANAGER,
    ROLE_WAREHOUSE,
)
from erp.permissions import ROLE_LABELS
from erp.services import users as user_service
from erp.ui.components import page_header, section

admin = require_role(ROLE_ADMIN)
page_header("Users", "Manage who can access the ERP and their role.", "Administration")

if flash := st.session_state.pop("user_flash", None):
    st.success(flash)

with session_scope() as session:
    users = user_service.list_users(session)

left, right = st.columns([1.6, 1], gap="large")
with left:
    section("All users")
    f1, f2, f3, f4 = st.columns(
        [1.4, 1, 1, 1], vertical_alignment="bottom"
    )
    user_search = f1.text_input("Search users", placeholder="Username, name, or email")
    user_role = f2.selectbox("Role filter", ["All", *sorted({u.role for u in users})])
    user_active = f3.selectbox("Account status", ["All", "Active", "Inactive"])
    user_sort = f4.selectbox(
        "Sort users", ["Name", "Newest account", "Oldest account"]
    )
    visible_users = [
        u for u in users
        if (not user_search.strip() or user_search.casefold() in u.username.casefold()
            or user_search.casefold() in u.name.casefold()
            or user_search.casefold() in u.email.casefold())
        and (user_role == "All" or u.role == user_role)
        and (user_active == "All" or u.active == (user_active == "Active"))
    ]
    visible_users.sort(key=lambda u: u.name.casefold() if user_sort == "Name" else u.created_at,
                       reverse=user_sort == "Newest account")
    st.dataframe(
        [
            {"Username": u.username, "Name": u.name, "Email": u.email, "Role": ROLE_LABELS[u.role],
             "Active": u.active, "Created": u.created_at}
            for u in visible_users
        ],
        hide_index=True,
        column_config={"Created": st.column_config.DatetimeColumn(format="DD MMM YYYY")},
    )
    section("Manage account")
    target = st.selectbox("User", users, format_func=lambda u: f"{u.name} ({u.username})")
    if target:
        with st.form("manage_user"):
            new_pw = st.text_input("New password (leave blank to keep)", type="password")
            active = st.checkbox("Active", value=target.active)
            if st.form_submit_button("Update", type="primary"):
                try:
                    with session_scope() as session:
                        if new_pw:
                            user_service.set_password(session, target.id, new_pw)
                        if active != target.active:
                            user_service.set_active(session, target.id, active, admin.id)
                    st.session_state["user_flash"] = f"{target.name} updated."
                    st.rerun()
                except user_service.UserError as exc:
                    st.error(str(exc))

with right:
    section("Add user")
    with st.form("add_user", clear_on_submit=True, border=True):
        username = st.text_input("Username *")
        name = st.text_input("Full name *")
        email = st.text_input("Email *")
        role = st.selectbox(
            "Role",
            [ROLE_SALES, ROLE_SALES_MANAGER, ROLE_ACCOUNTS, ROLE_WAREHOUSE, ROLE_ADMIN],
            format_func=ROLE_LABELS.get,
        )
        password = st.text_input("Password *", type="password", help="At least 8 characters")
        if st.form_submit_button("Create user", type="primary", width="stretch"):
            try:
                with session_scope() as session:
                    user_service.create_user(session, username=username, name=name, email=email,
                                             password=password, role=role)
                st.session_state["user_flash"] = f"User {username.strip().lower()} created."
                st.rerun()
            except user_service.UserError as exc:
                st.error(str(exc))
