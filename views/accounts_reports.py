from datetime import date

import pandas as pd
import streamlit as st
from sqlalchemy import select

from erp.auth import require_role
from erp.db import session_scope
from erp.models import Customer, ROLE_ACCOUNTS, ROLE_ADMIN, SalesInvoice
from erp.services import predictions
from erp.ui.components import compact_currency, kpi_row, page_header, section

require_role(ROLE_ADMIN, ROLE_ACCOUNTS)
page_header("Receivables", "Outstanding balances, overdue invoices and aging buckets.", "Accounts")

with session_scope() as session:
    records = list(session.execute(
        select(SalesInvoice, Customer)
        .join(Customer, Customer.id == SalesInvoice.customer_id)
        .where(SalesInvoice.status.in_(["ISSUED", "PARTIALLY_PAID"]))
        .order_by(SalesInvoice.due_date)
    ))
    risk = predictions.invoice_risk_map(session)

rows = []
today = date.today()
for invoice, customer in records:
    due = invoice.due_date.date() if invoice.due_date else invoice.invoice_date.date()
    days = max(0, (today - due).days)
    bucket = "Current" if due >= today else "1-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
    rows.append({
        "Invoice": invoice.invoice_no, "Customer": customer.name, "Region": customer.region,
        "Invoice date": invoice.invoice_date.date(), "Due date": due,
        "Days overdue": days, "Aging": bucket,
        "Invoice total": float(invoice.total), "Paid": float(invoice.amount_paid),
        "Credits": float(invoice.credit_total), "Debits": float(invoice.debit_total),
        "Outstanding": float(invoice.balance_due),
        "Late risk": risk.get(invoice.id, (None, ""))[0],
        "Risk band": risk.get(invoice.id, (None, ""))[1],
    })

df = pd.DataFrame(rows)
if df.empty:
    st.info("There are no open receivables.")
else:
    outstanding = float(df["Outstanding"].sum())
    overdue = float(df.loc[df["Days overdue"] > 0, "Outstanding"].sum())
    customers = int(df.loc[df["Outstanding"] > 0, "Customer"].nunique())
    kpi_row([
        ("Outstanding", compact_currency(outstanding), f"{len(df)} invoices"),
        ("Overdue", compact_currency(overdue), f"{overdue / outstanding * 100:.1f}% of balance" if outstanding else "", "amber"),
        ("Customers", str(customers), "With open balance", "navy"),
    ])
    section("Aging summary")
    summary = df.groupby("Aging", sort=False).agg(
        Invoices=("Invoice", "count"), Customers=("Customer", "nunique"),
        Outstanding=("Outstanding", "sum"),
    ).reindex(["Current", "1-30", "31-60", "61-90", "90+"]).fillna(0).reset_index()
    st.dataframe(summary, hide_index=True, column_config={
        "Outstanding": st.column_config.NumberColumn(format="₹%.2f"),
    })
    section("Open invoices")
    high_only = st.toggle("Show only HIGH late-payment risk", disabled=not risk)
    st.dataframe(df[df["Risk band"] == "HIGH"] if high_only else df, hide_index=True, height=440, column_config={
        "Late risk": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "Invoice date": st.column_config.DateColumn(format="DD MMM YYYY"),
        "Due date": st.column_config.DateColumn(format="DD MMM YYYY"),
        "Invoice total": st.column_config.NumberColumn(format="₹%.2f"),
        "Paid": st.column_config.NumberColumn(format="₹%.2f"),
        "Credits": st.column_config.NumberColumn(format="₹%.2f"),
        "Debits": st.column_config.NumberColumn(format="₹%.2f"),
        "Outstanding": st.column_config.NumberColumn(format="₹%.2f"),
    })
    st.download_button("Download aging report", df.to_csv(index=False), "receivables-aging.csv",
                       "text/csv", type="primary")
