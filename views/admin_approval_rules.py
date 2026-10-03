from decimal import Decimal

import streamlit as st

from erp.auth import require_role
from erp.db import session_scope
from erp.models import ROLE_ADMIN, ROLE_SALES_MANAGER
from erp.permissions import ROLE_LABELS
from erp.services import users
from erp.services.users import UserError
from erp.ui.components import page_header, section

admin = require_role(ROLE_ADMIN)
page_header("Approval Rules", "Route high-value and high-discount orders to the right approver.", "Administration")

if message := st.session_state.pop("approval_rule_flash", None):
    st.success(message)

with session_scope() as session:
    rules = users.list_approval_rules(session)

section("Active rules")
if rules:
    st.dataframe(
        [{"Name": rule.name, "Condition": "Order value" if rule.rule_type == "ORDER_VALUE" else "Discount %",
          "Threshold": float(rule.threshold), "Approver": ROLE_LABELS.get(rule.approver_role, rule.approver_role),
          "Active": rule.active} for rule in rules],
        hide_index=True,
    )
else:
    st.info("No extra rules yet. All orders route to a Sales Manager; credit exceptions are flagged for review.")

section("Add or edit rule")
selected = st.selectbox(
    "Existing rule", [None, *rules],
    format_func=lambda r: "Create new rule" if r is None else r.name,
)
with st.form("approval_rule_form", border=True):
    name = st.text_input("Rule name", value=selected.name if selected else "")
    rule_type = st.selectbox(
        "Condition", ["ORDER_VALUE", "DISCOUNT_PCT"],
        format_func=lambda x: "Order value (INR)" if x == "ORDER_VALUE" else "Line/order discount (%)",
        index=0 if not selected or selected.rule_type == "ORDER_VALUE" else 1,
    )
    default_threshold = float(selected.threshold) if selected else 500000.0
    threshold = st.number_input(
        "Threshold", min_value=0.01, step=10000.0 if rule_type == "ORDER_VALUE" else 0.5,
        value=default_threshold,
    )
    role_options = [ROLE_SALES_MANAGER, ROLE_ADMIN]
    approver_role = st.selectbox(
        "Required approver", role_options,
        format_func=ROLE_LABELS.get,
        index=role_options.index(selected.approver_role) if selected and selected.approver_role in role_options else 0,
    )
    active = st.checkbox("Active", value=selected.active if selected else True)
    if st.form_submit_button("Save rule", type="primary"):
        try:
            with session_scope() as session:
                users.save_approval_rule(
                    session, actor_id=admin.id, name=name, rule_type=rule_type,
                    threshold=Decimal(str(threshold)), approver_role=approver_role,
                    active=active, rule_id=selected.id if selected else None,
                )
            st.session_state["approval_rule_flash"] = f"Approval rule {name.strip()} saved."
            st.rerun()
        except UserError as exc:
            st.error(str(exc))
