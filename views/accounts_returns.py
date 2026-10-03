from decimal import Decimal

import streamlit as st
from sqlalchemy import select

from erp.auth import require_role
from erp.db import session_scope
from erp.models import (
    InvoiceItem, ROLE_ACCOUNTS, ROLE_ADMIN, ROLE_SALES_MANAGER,
    ROLE_WAREHOUSE, Product, SalesInvoice,
)
from erp.services import returns
from erp.services.returns import REASONS, ReturnError
from erp.ui.components import currency, page_header, section

user = require_role(ROLE_ADMIN, ROLE_ACCOUNTS, ROLE_SALES_MANAGER, ROLE_WAREHOUSE)
page_header("Returns and Credit Notes", "Request, approve, receive and financially settle returned goods.", "Sales Operations")

if message := st.session_state.pop("return_flash", None):
    st.success(message)

with session_scope() as session:
    invoices = list(session.scalars(
        select(SalesInvoice).where(SalesInvoice.status.in_(["ISSUED", "PARTIALLY_PAID", "PAID"]))
        .order_by(SalesInvoice.invoice_date.desc())
    ))
    return_rows = [(r.id, r.return_no, r.status, r.reason, r.invoice_id) for r in returns.list_returns(session)]
    notes = returns.list_credit_notes(session)

if user.role in {ROLE_ADMIN, ROLE_ACCOUNTS} and invoices:
    section("Request sales return")
    invoice = st.selectbox("Invoice", invoices, format_func=lambda i: f"{i.invoice_no} · {currency(float(i.total))}")
    with session_scope() as session:
        items = list(session.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)))
        products = {item.id: session.get(Product, item.product_id).name for item in items}
    with st.form("return_request", border=True):
        reason = st.selectbox("Reason", REASONS)
        quantities = {}
        for item in items:
            col1, col2 = st.columns([3, 1])
            col1.write(f"{products[item.id]} · invoiced {item.qty}")
            quantities[item.id] = col2.number_input(
                "Return qty", min_value=0, max_value=item.qty, value=0, key=f"return_qty_{item.id}"
            )
        restock = st.checkbox("Return good-condition items to stock", value=True)
        notes_text = st.text_input("Notes")
        if st.form_submit_button("Submit return request", type="primary"):
            try:
                with session_scope() as session:
                    request = returns.create_return(
                        session, invoice_id=invoice.id, actor_id=user.id,
                        quantities={item_id: int(qty) for item_id, qty in quantities.items() if qty},
                        reason=reason, notes=notes_text, restock=restock,
                    )
                    return_no = request.return_no
                st.session_state["return_flash"] = f"Return request {return_no} created."
                st.rerun()
            except ReturnError as exc:
                st.error(str(exc))

section("Return workflow")
if not return_rows:
    st.info("No return requests exist.")
else:
    r1, r2, r3 = st.columns(
        [1.5, 1, 1], vertical_alignment="bottom"
    )
    return_search = r1.text_input("Search returns", placeholder="Return number or reason")
    return_status = r2.selectbox("Return status", ["All", *sorted({row[2] for row in return_rows})])
    return_sort = r3.selectbox("Sort returns", ["Newest", "Oldest"])
    visible_returns = [
        row for row in return_rows
        if (return_status == "All" or row[2] == return_status)
        and (not return_search.strip() or return_search.casefold() in row[1].casefold()
             or return_search.casefold() in row[3].casefold())
    ]
    visible_returns.sort(key=lambda row: row[0], reverse=return_sort == "Newest")
for return_id, return_no, status, reason, invoice_id in visible_returns if return_rows else []:
    with st.container(border=True):
        st.markdown(f"**{return_no}** · Invoice #{invoice_id} · {status} · {reason}")
        cols = st.columns(4)
        if status == "REQUESTED" and user.role in {ROLE_ADMIN, ROLE_SALES_MANAGER}:
            if cols[0].button("Approve", key=f"return_approve_{return_id}", type="primary"):
                try:
                    with session_scope() as session:
                        returns.decide_return(session, return_id, user.id, approve=True)
                    st.session_state["return_flash"] = f"Return {return_no} approved."
                    st.rerun()
                except ReturnError as exc:
                    st.error(str(exc))
            reject_reason = cols[1].text_input("Reason to reject", key=f"return_reject_reason_{return_id}")
            if cols[2].button("Reject", key=f"return_reject_{return_id}", disabled=not reject_reason.strip()):
                try:
                    with session_scope() as session:
                        returns.decide_return(session, return_id, user.id, approve=False, reason=reject_reason)
                    st.session_state["return_flash"] = f"Return {return_no} rejected."
                    st.rerun()
                except ReturnError as exc:
                    st.error(str(exc))
        if status == "APPROVED" and user.role in {ROLE_ADMIN, ROLE_WAREHOUSE}:
            if cols[0].button("Confirm goods received", key=f"return_receive_{return_id}"):
                try:
                    with session_scope() as session:
                        returns.receive_return(session, return_id, user.id)
                    st.session_state["return_flash"] = f"Goods received for {return_no}; stock ledger updated."
                    st.rerun()
                except ReturnError as exc:
                    st.error(str(exc))
        if status == "RECEIVED" and user.role in {ROLE_ADMIN, ROLE_ACCOUNTS}:
            if cols[0].button("Create credit note", key=f"credit_create_{return_id}"):
                try:
                    with session_scope() as session:
                        note = returns.create_credit_note(session, return_id, user.id)
                        note_id, note_no = note.id, note.note_no
                    with session_scope() as session:
                        returns.issue_credit_note(session, note_id, user.id)
                    st.session_state["return_flash"] = f"Credit note {note_no} issued."
                    st.rerun()
                except ReturnError as exc:
                    st.error(str(exc))

section("Credit notes")
if notes:
    st.dataframe(
        [{"Credit note": note.note_no, "Invoice": note.invoice_id, "Status": note.status,
          "Reason": note.reason, "Total": float(note.total), "Created": note.created_at}
         for note in notes],
        hide_index=True,
        column_config={
            "Total": st.column_config.NumberColumn(format="₹%.2f"),
            "Created": st.column_config.DatetimeColumn(format="DD MMM YYYY HH:mm"),
        },
    )
else:
    st.caption("No credit notes have been issued.")

if user.role in {ROLE_ADMIN, ROLE_ACCOUNTS} and invoices:
    with st.expander("Create debit note"):
        invoice = st.selectbox(
            "Invoice for debit note", invoices,
            format_func=lambda item: f"{item.invoice_no} · balance {currency(float(item.balance_due))}",
            key="debit_invoice",
        )
        with session_scope() as session:
            invoice_items = list(session.scalars(
                select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
            ))
            item_labels = [(item.id, session.get(Product, item.product_id).name) for item in invoice_items]
        if item_labels:
            with st.form("debit_note_form"):
                item_choice = st.selectbox("Invoice line", item_labels, format_func=lambda row: row[1])
                taxable_amount = st.number_input("Additional taxable amount (INR)", min_value=0.01, step=100.0)
                reason = st.text_input("Reason")
                if st.form_submit_button("Issue debit note", type="primary"):
                    try:
                        with session_scope() as session:
                            note = returns.create_debit_note(
                                session, invoice_id=invoice.id, invoice_item_id=item_choice[0],
                                actor_id=user.id, taxable_amount=Decimal(str(taxable_amount)),
                                reason=reason,
                            )
                            returns.issue_credit_note(session, note.id, user.id)
                            note_no = note.note_no
                        st.session_state["return_flash"] = f"Debit note {note_no} issued."
                        st.rerun()
                    except ReturnError as exc:
                        st.error(str(exc))
