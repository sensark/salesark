import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import select

from erp import config
from erp.auth import require_role
from erp.db import session_scope
from erp.email_client import EmailClient
from erp.models import ROLE_ADMIN, EmailLog
from erp.services import emails
from erp.ui.components import hint, kpi_row, page_header, section

admin = require_role(ROLE_ADMIN)
page_header("Email Log", "Every email the system has attempted to send.", "Administration")

client = EmailClient()
if not config.EMAIL_ENABLED:
    hint("Email sending is disabled (EMAIL_ENABLED=false). Messages are logged but not delivered.")
elif not client.configured:
    hint("SMTP is not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD and SMTP_FROM in .env.", "warn")
else:
    hint(f"Sending via {config.SMTP_HOST}:{config.SMTP_PORT} as {config.SMTP_FROM}", "ok")

for level, msg in st.session_state.pop("email_flash", []):
    getattr(st, level)(msg)

with session_scope() as session:
    logs = list(session.scalars(select(EmailLog).order_by(EmailLog.created_at.desc()).limit(500)))

kpi_row([
    ("Sent", str(sum(l.status == "SENT" for l in logs)), "Delivered to SMTP", "green"),
    ("Failed", str(sum(l.status == "FAILED" for l in logs)), "Need attention", "amber"),
    ("Skipped", str(sum(l.status == "SKIPPED" for l in logs)), "Sending disabled", "navy"),
])

tab_log, tab_test = st.tabs(["History", "Send test email"])
with tab_log:
    status = st.segmented_control("Status", ["All", "SENT", "FAILED", "SKIPPED"], default="All")
    e1, e2 = st.columns([2, 1], vertical_alignment="bottom")
    search = e1.text_input("Search email history", placeholder="Recipient, subject, or type")
    ordering = e2.selectbox("Sort email history", ["Newest", "Oldest"])
    needle = search.casefold().strip()
    shown = [
        log for log in logs
        if (status in (None, "All") or log.status == status)
        and (not needle or needle in log.to_address.casefold()
             or needle in log.subject.casefold() or needle in log.kind.casefold())
    ]
    shown.sort(key=lambda log: log.created_at, reverse=ordering == "Newest")
    event = st.dataframe(
        [
            {"When": l.created_at, "Status": l.status, "Type": l.kind.replace("_", " ").title(),
             "To": l.to_address, "Subject": l.subject, "Error": l.error or ""}
            for l in shown
        ],
        hide_index=True, height=420, on_select="rerun", selection_mode="single-row",
        column_config={"When": st.column_config.DatetimeColumn(format="DD MMM YYYY HH:mm:ss")},
    )
    if event.selection.rows:
        entry = shown[event.selection.rows[0]]
        section(entry.subject)
        c1, _ = st.columns([1, 4])
        if c1.button("Resend", type="primary", width="stretch"):
            with st.spinner("Sending..."):
                result = emails.resend(entry.id)
            st.session_state["email_flash"] = (
                [("success", "Email resent.")] if result.ok else [("error", f"Resend failed: {result.error}")]
            )
            st.rerun()
        with st.expander("Preview", expanded=True):
            components.html(entry.html_body, height=560, scrolling=True)

with tab_test:
    with st.form("test_email"):
        to = st.text_input("Recipient", value=admin.email)
        if st.form_submit_button("Send test email", type="primary"):
            result = client.send(
                to, f"Test email from {config.COMPANY_NAME} Sales ERP",
                "<p>This is a test email from the Sales ERP. SMTP is configured correctly.</p>",
                "This is a test email from the Sales ERP. SMTP is configured correctly.",
            )
            if result.skipped:
                st.info("Email sending is disabled; nothing was sent.")
            elif result.ok:
                st.success(f"Test email sent to {to}.")
            else:
                st.error(f"Failed: {result.error}")
