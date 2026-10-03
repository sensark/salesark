from html import escape

import streamlit as st

from erp import config
from erp.auth import get_authenticator, load_current_user
from erp.db import init_db, session_scope
from erp.models import (
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    ROLE_SALES,
    ROLE_SALES_MANAGER,
    ROLE_WAREHOUSE,
    STATUS_PENDING,
    Order,
)
from erp.services import notifications
from erp.services import users as user_service
from erp.services.users import UserError
from erp.ui.theme import apply_theme

st.set_page_config(page_title=f"{config.COMPANY_NAME} | Sales ERP", layout="wide", initial_sidebar_state="expanded")
apply_theme()
init_db()


def _on_logout(_=None) -> None:
    for key in ("current_user", "cart", "order_customer_id"):
        st.session_state.pop(key, None)


def _login(authenticator) -> None:
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown(
            f"""<div class="login-brand"><div class="logo">SE</div>
            <h2>{escape(config.COMPANY_NAME)}</h2><p>Sales ERP &middot; Sign in to continue</p></div>""",
            unsafe_allow_html=True,
        )
        authenticator.login(location="main", fields={"Form name": "Sign in", "Login": "Sign in"})
        if st.session_state.get("authentication_status") is False:
            st.error("Incorrect username or password.")


def _first_admin_setup() -> None:
    _, middle, _ = st.columns([1, 1.2, 1])
    with middle:
        st.markdown(
            f'<div class="login-brand"><div class="logo">KE</div>'
            f'<h2>{escape(config.COMPANY_NAME)}</h2><p>Initial administrator setup</p></div>',
            unsafe_allow_html=True,
        )
        with st.form("first_admin_setup", border=True):
            username = st.text_input("Admin username", value="admin")
            name = st.text_input("Full name")
            email = st.text_input("Work email")
            password = st.text_input("Password", type="password", help="Use at least 8 characters.")
            confirm = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create Admin account", type="primary", width="stretch")
        if submitted:
            if password != confirm:
                st.error("Passwords do not match.")
                return
            try:
                with session_scope() as session:
                    user_service.create_first_admin(
                        session, username=username, name=name, email=email, password=password,
                    )
            except UserError as exc:
                st.error(str(exc))
                return
            st.success("Admin account created. Sign in with the credentials you just entered.")


def _sidebar(authenticator, user) -> None:
    with session_scope() as session:
        unread = notifications.unread_count(session, user.id)
        pending_query = session.query(Order).filter(Order.status == STATUS_PENDING)
        if user.role == ROLE_SALES_MANAGER:
            pending_query = pending_query.filter(Order.required_approver_role == ROLE_SALES_MANAGER)
        pending = pending_query.count() if user.role in {ROLE_ADMIN, ROLE_SALES_MANAGER} else 0
    with st.sidebar:
        st.markdown(
            f'<div class="side-brand">Krypton<span> ERP</span></div>'
            f'<div class="side-user"><div class="n">{escape(user.name)}</div>'
            f'<div class="r">{escape(user.role_label)}</div></div>',
            unsafe_allow_html=True,
        )
        info = f"Notifications<span class='bell'>{unread}</span>"
        if user.role in {ROLE_ADMIN, ROLE_SALES_MANAGER}:
            info += f"&nbsp;&nbsp;Pending<span class='bell'>{pending}</span>"
        st.markdown(f"<div style='margin:4px 0 14px 2px;font-size:13px'>{info}</div>", unsafe_allow_html=True)


def main() -> None:
    with session_scope() as session:
        has_users = bool(user_service.list_users(session, active_only=True))
    if not has_users:
        _first_admin_setup()
        return

    authenticator = get_authenticator()
    user = load_current_user()
    if user is None:
        if st.session_state.get("authentication_status"):
            # Cookie refers to a user who no longer exists or was deactivated.
            authenticator.logout(location="unrendered", callback=_on_logout)
        _login(authenticator)
        return

    _sidebar(authenticator, user)

    inbox = st.Page("views/inbox.py", title="Notifications", icon=":material/notifications:", url_path="inbox")
    if user.role == ROLE_ADMIN:
        pages = {
            "Operations": [
                st.Page("views/admin_approvals.py", title="Order Approvals", icon=":material/fact_check:", default=True),
                st.Page("views/admin_analytics.py", title="Analytics", icon=":material/monitoring:"),
                st.Page("views/admin_predictive.py", title="Predictive Insights", icon=":material/insights:"),
                st.Page("views/admin_reports.py", title="Sales and Finance Reports", icon=":material/assessment:"),
            ],
            "Management": [
                st.Page("views/admin_products.py", title="Products and Discounts", icon=":material/inventory_2:"),
                st.Page("views/admin_pricing.py", title="Pricing Rules", icon=":material/price_change:"),
                st.Page("views/admin_users.py", title="Users", icon=":material/group:"),
                st.Page("views/admin_approval_rules.py", title="Approval Rules", icon=":material/rule:"),
                st.Page("views/admin_email_log.py", title="Email Log", icon=":material/mail:"),
            ],
            "Sales": [
                st.Page("views/sales_dashboard.py", title="Sales Dashboard", icon=":material/dashboard:"),
                st.Page("views/sales_new_order.py", title="New Order", icon=":material/add_shopping_cart:"),
                st.Page("views/sales_customers.py", title="Customers", icon=":material/contacts:"),
                st.Page("views/sales_quotations.py", title="Quotations", icon=":material/request_quote:"),
                st.Page("views/sales_my_orders.py", title="Sales Orders", icon=":material/receipt_long:"),
            ],
            "Accounts": [
                st.Page("views/accounts_invoices.py", title="Invoices", icon=":material/receipt_long:"),
                st.Page("views/accounts_payments.py", title="Payments", icon=":material/payments:"),
                st.Page("views/accounts_returns.py", title="Returns and Credit Notes", icon=":material/assignment_return:"),
                st.Page("views/accounts_reports.py", title="Receivables", icon=":material/account_balance:"),
                st.Page("views/accounts_accounting.py", title="Accounting Export", icon=":material/account_balance_wallet:"),
            ],
            "Warehouse": [
                st.Page("views/warehouse_deliveries.py", title="Deliveries", icon=":material/local_shipping:"),
                st.Page("views/warehouse_stock.py", title="Stock Movements", icon=":material/inventory_2:"),
            ],
            "Account": [inbox],
        }
    elif user.role in {ROLE_SALES, ROLE_SALES_MANAGER}:
        pages = {
            "Sales": [
                st.Page("views/sales_dashboard.py", title="Sales Dashboard", icon=":material/dashboard:", default=True),
                st.Page("views/sales_new_order.py", title="New Order", icon=":material/add_shopping_cart:"),
                st.Page("views/sales_customers.py", title="Customers", icon=":material/contacts:"),
                st.Page("views/sales_quotations.py", title="Quotations", icon=":material/request_quote:"),
                st.Page("views/sales_my_orders.py", title="My Orders", icon=":material/receipt_long:"),
            ],
            **({"Management": [
                st.Page("views/admin_approvals.py", title="Order Approvals", icon=":material/fact_check:"),
                st.Page("views/admin_analytics.py", title="Sales Analytics", icon=":material/monitoring:"),
                st.Page("views/admin_predictive.py", title="Predictive Insights", icon=":material/insights:"),
                st.Page("views/admin_reports.py", title="Sales Reports", icon=":material/assessment:"),
                st.Page("views/accounts_returns.py", title="Returns Review", icon=":material/assignment_return:"),
            ]} if user.role == ROLE_SALES_MANAGER else {}),
            "Account": [inbox],
        }
    elif user.role == ROLE_ACCOUNTS:
        pages = {
            "Accounts": [
                st.Page("views/accounts_invoices.py", title="Invoices", icon=":material/receipt_long:", default=True),
                st.Page("views/accounts_payments.py", title="Payments", icon=":material/payments:"),
                st.Page("views/accounts_returns.py", title="Returns and Credit Notes", icon=":material/assignment_return:"),
                st.Page("views/accounts_reports.py", title="Receivables", icon=":material/account_balance:"),
                st.Page("views/admin_reports.py", title="Sales and Tax Reports", icon=":material/assessment:"),
                st.Page("views/accounts_accounting.py", title="Accounting Export", icon=":material/account_balance_wallet:"),
            ],
            "Account": [inbox],
        }
    elif user.role == ROLE_WAREHOUSE:
        pages = {
            "Warehouse": [
                st.Page("views/warehouse_deliveries.py", title="Deliveries", icon=":material/local_shipping:", default=True),
                st.Page("views/warehouse_stock.py", title="Stock Movements", icon=":material/inventory_2:"),
                st.Page("views/accounts_returns.py", title="Return Receipts", icon=":material/assignment_return:"),
            ],
            "Account": [inbox],
        }

    nav = st.navigation(pages)
    with st.sidebar:
        st.divider()
        authenticator.logout("Sign out", location="sidebar", callback=_on_logout)
    nav.run()


main()
