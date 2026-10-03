from datetime import date

import pandas as pd
import streamlit as st

from erp.auth import require_role
from erp.db import session_scope
from erp.models import ROLE_ACCOUNTS, ROLE_ADMIN
from erp.services import accounting_export
from erp.services.accounting_export import AccountingExportError, DEFAULT_MAPPINGS
from erp.ui.components import page_header

user = require_role(ROLE_ADMIN, ROLE_ACCOUNTS)
page_header("Accounting Export", "Map accounts, preview balanced journals and export CSV for posting.", "Accounts")

if message := st.session_state.pop("export_flash", None):
    st.success(message)

with session_scope() as session:
    mappings = accounting_export.list_mappings(session)
    exports = accounting_export.list_exports(session)

mapping_tab, journal_tab, history_tab = st.tabs(["Account mappings", "Journal preview", "Export history"])
with mapping_tab:
    existing = {mapping.mapping_key: mapping for mapping in mappings}
    st.dataframe(
        [{"Key": key, "Account code": existing[key].account_code if key in existing else "",
          "Account name": existing[key].account_name if key in existing else "Not configured",
          "Active": existing[key].active if key in existing else False}
         for key in DEFAULT_MAPPINGS],
        hide_index=True,
    )
    col1, col2 = st.columns(2)
    if col1.button("Load sample account mappings", disabled=bool(mappings)):
        try:
            with session_scope() as session:
                accounting_export.seed_default_mappings(session, user.id)
            st.session_state["export_flash"] = "Sample mappings loaded. Replace them with Krypton chart-of-accounts values."
            st.rerun()
        except AccountingExportError as exc:
            st.error(str(exc))
    with st.form("mapping_form", border=True):
        key = st.selectbox("Mapping", list(DEFAULT_MAPPINGS))
        default_code, default_name = DEFAULT_MAPPINGS[key]
        current = existing.get(key)
        account_code = st.text_input("Account code", value=current.account_code if current else default_code)
        account_name = st.text_input("Account name", value=current.account_name if current else default_name)
        active = st.checkbox("Active", value=current.active if current else True)
        if st.form_submit_button("Save mapping", type="primary"):
            try:
                with session_scope() as session:
                    accounting_export.save_mapping(
                        session, actor_id=user.id, mapping_key=key,
                        account_code=account_code, account_name=account_name, active=active,
                    )
                st.session_state["export_flash"] = f"Mapping {key} saved."
                st.rerun()
            except AccountingExportError as exc:
                st.error(str(exc))

with journal_tab:
    default_start = date(date.today().year, 1, 1)
    selected_period = st.date_input("Posting date range", (default_start, date.today()))
    start, end = selected_period if isinstance(selected_period, tuple) else (default_start, date.today())
    if st.button("Build journal preview", type="primary"):
        try:
            with session_scope() as session:
                rows = accounting_export.build_journal(session, start, end)
            st.session_state["journal_preview"] = rows
        except AccountingExportError as exc:
            st.error(str(exc))
    rows = st.session_state.get("journal_preview", [])
    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(frame, hide_index=True, column_config={
            "debit": st.column_config.NumberColumn(format="₹%.2f"),
            "credit": st.column_config.NumberColumn(format="₹%.2f"),
        })
        debits, credits = frame["debit"].sum(), frame["credit"].sum()
        st.caption(f"Debits ₹{debits:,.2f} · Credits ₹{credits:,.2f} · {len(rows)} journal lines")
        if st.button("Generate and download CSV", type="primary"):
            try:
                with session_scope() as session:
                    export, csv_data = accounting_export.create_export(
                        session, actor_id=user.id, start=start, end=end,
                    )
                    export_no = export.export_no
                st.session_state["export_file"] = csv_data
                st.session_state["export_file_name"] = export.file_name
                st.session_state["export_flash"] = f"Export {export_no} generated."
                st.rerun()
            except AccountingExportError as exc:
                st.error(str(exc))
    if st.session_state.get("export_file"):
        st.download_button(
            "Download journal CSV", st.session_state["export_file"],
            st.session_state["export_file_name"], "text/csv",
        )

with history_tab:
    h1, h2, h3 = st.columns(
        [1.5, 1, 1], vertical_alignment="bottom"
    )
    export_search = h1.text_input("Search exports", placeholder="Export number or filename")
    export_status = h2.selectbox("Export status", ["All", *sorted({row.status for row in exports})])
    export_sort = h3.selectbox("Sort exports", ["Newest", "Oldest"])
    visible_exports = [
        row for row in exports
        if (export_status == "All" or row.status == export_status)
        and (not export_search.strip()
             or export_search.casefold() in row.export_no.casefold()
             or export_search.casefold() in row.file_name.casefold())
    ]
    visible_exports.sort(key=lambda row: row.exported_at, reverse=export_sort == "Newest")
    st.dataframe(
        [{"Export": row.export_no, "From": row.date_from.date(), "To": row.date_to.date(),
          "Status": row.status, "File": row.file_name, "Rows": row.row_count, "Created": row.exported_at}
         for row in visible_exports],
        hide_index=True,
        column_config={
            "From": st.column_config.DateColumn(format="DD MMM YYYY"),
            "To": st.column_config.DateColumn(format="DD MMM YYYY"),
            "Created": st.column_config.DatetimeColumn(format="DD MMM YYYY HH:mm"),
        },
    )
