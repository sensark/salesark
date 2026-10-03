"""Render every view headlessly with a fake logged-in user to catch runtime errors."""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from erp.auth import CurrentUser  # noqa: E402
from erp.db import session_scope  # noqa: E402
from erp.services.users import get_by_username  # noqa: E402

VIEWS = {
    "admin": [
        "admin_approvals", "admin_analytics", "admin_predictive", "admin_reports", "admin_products", "admin_users",
        "admin_email_log", "admin_approval_rules", "sales_dashboard", "sales_new_order",
        "sales_customers", "sales_quotations", "sales_my_orders", "accounts_invoices",
        "accounts_payments", "accounts_returns", "accounts_reports", "accounts_accounting",
        "warehouse_deliveries", "warehouse_stock", "inbox",
    ],
    "rahul.sharma": [
        "sales_dashboard", "sales_new_order", "sales_customers", "sales_quotations",
        "sales_my_orders", "inbox",
    ],
    "sales.manager": [
        "sales_dashboard", "sales_new_order", "sales_customers", "sales_quotations",
        "sales_my_orders", "admin_approvals", "admin_analytics", "admin_predictive", "admin_reports", "accounts_returns", "inbox",
    ],
    "accounts.demo": [
        "accounts_invoices", "accounts_payments", "accounts_returns", "accounts_reports",
        "accounts_accounting", "admin_reports", "inbox",
    ],
    "warehouse.demo": ["warehouse_deliveries", "warehouse_stock", "accounts_returns", "inbox"],
}
DENIED = {
    "admin": [],
    "rahul.sharma": ["admin_analytics", "admin_predictive", "admin_approvals", "accounts_invoices", "warehouse_stock"],
    "sales.manager": ["admin_users", "accounts_payments", "warehouse_stock"],
    "accounts.demo": ["admin_analytics", "admin_predictive", "sales_new_order", "warehouse_stock"],
    "warehouse.demo": ["admin_analytics", "admin_predictive", "sales_new_order", "accounts_payments"],
}

failed = False
for username in VIEWS:
    with session_scope() as s:
        u = get_by_username(s, username)
        cu = CurrentUser(u.id, u.username, u.name, u.email, u.role)
    for view in VIEWS[username] + DENIED.get(username, []):
        expect_denied = view in DENIED.get(username, [])
        at = AppTest.from_file(str(ROOT / "views" / f"{view}.py"), default_timeout=180)
        at.session_state["current_user"] = cu
        if view == "sales_new_order":
            at.session_state["order_customer_id"] = 1
            at.session_state["cart"] = {1: 8, 6: 3}
        at.run()
        errors = [e.value for e in at.error] + [str(x.value) for x in at.exception]
        denied = any("permission" in e for e in errors)
        ok = denied if expect_denied else not errors
        label = "denied (expected)" if expect_denied and denied else ("ok" if ok else "FAIL: " + " | ".join(errors))
        print(f"{username:12} {view:18} {label}")
        failed |= not ok

at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
at.run()
login_ok = not at.exception and any(b.label == "Sign in" for b in at.button)
print(f"{'anonymous':12} {'app (login)':18} {'ok' if login_ok else 'FAIL'}")
failed |= not login_ok
sys.exit(1 if failed else 0)
