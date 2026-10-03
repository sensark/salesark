import csv
import io
import secrets
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.models import (
    AccountingExport,
    AccountingMapping,
    CreditNote,
    Payment,
    PaymentAllocation,
    SalesInvoice,
    User,
)
from erp.permissions import require_action
from erp.services import audit
from erp.services.discounts import money


class AccountingExportError(ValueError):
    pass


DEFAULT_MAPPINGS = {
    "ACCOUNTS_RECEIVABLE": ("1100", "Trade Receivables"),
    "SALES_REVENUE": ("4000", "Sales Revenue"),
    "SALES_RETURNS": ("4050", "Sales Returns"),
    "OUTPUT_CGST": ("2201", "Output CGST"),
    "OUTPUT_SGST": ("2202", "Output SGST"),
    "OUTPUT_IGST": ("2203", "Output IGST"),
    "OUTPUT_CESS": ("2204", "Output Cess"),
    "CASH": ("1000", "Cash"),
    "BANK_TRANSFER": ("1010", "Bank"),
    "UPI": ("1011", "UPI Clearing"),
    "CHEQUE": ("1012", "Cheques in Hand"),
    "CARD": ("1013", "Card Clearing"),
    "OTHER": ("1019", "Other Receipts"),
}


def _actor(session: Session, actor_id: int) -> User:
    actor = session.get(User, actor_id)
    if actor is None:
        raise AccountingExportError("User not found.")
    try:
        require_action(actor.role, "accounting.export")
    except PermissionError as exc:
        raise AccountingExportError(str(exc)) from exc
    return actor


def list_mappings(session: Session) -> list[AccountingMapping]:
    return list(session.scalars(select(AccountingMapping).order_by(AccountingMapping.mapping_key)))


def save_mapping(
    session: Session,
    *,
    actor_id: int,
    mapping_key: str,
    account_code: str,
    account_name: str,
    active: bool = True,
) -> AccountingMapping:
    _actor(session, actor_id)
    mapping_key, account_code, account_name = (
        mapping_key.strip().upper(), account_code.strip(), account_name.strip()
    )
    if mapping_key not in DEFAULT_MAPPINGS:
        raise AccountingExportError("Unknown accounting mapping key.")
    if not account_code or not account_name:
        raise AccountingExportError("Account code and name are required.")
    mapping = session.scalar(
        select(AccountingMapping).where(AccountingMapping.mapping_key == mapping_key)
    )
    if mapping is None:
        mapping = AccountingMapping(mapping_key=mapping_key)
    mapping.account_code = account_code
    mapping.account_name = account_name
    mapping.active = active
    session.add(mapping)
    session.flush()
    audit.record(
        session, actor_id=actor_id, action="SAVE", entity_type="ACCOUNTING_MAPPING",
        entity_id=mapping.id, changes={"key": mapping_key, "account_code": account_code},
    )
    return mapping


def seed_default_mappings(session: Session, actor_id: int) -> None:
    existing = {m.mapping_key for m in list_mappings(session)}
    for key, (code, name) in DEFAULT_MAPPINGS.items():
        if key not in existing:
            save_mapping(
                session, actor_id=actor_id, mapping_key=key,
                account_code=code, account_name=name,
            )


def _mapping_map(session: Session) -> dict[str, AccountingMapping]:
    rows = list_mappings(session)
    return {row.mapping_key: row for row in rows if row.active}


def _add_line(
    rows: list[dict],
    mappings: dict[str, AccountingMapping],
    *,
    mapping_key: str,
    amount: Decimal,
    debit: bool,
    document_type: str,
    document_no: str,
    occurred_at: datetime,
    narration: str,
) -> None:
    amount = money(amount)
    if amount == 0:
        return
    mapping = mappings.get(mapping_key)
    if mapping is None:
        raise AccountingExportError(f"Configure active mapping {mapping_key} before exporting.")
    rows.append({
        "date": occurred_at.date().isoformat(),
        "document_type": document_type,
        "document_no": document_no,
        "account_code": mapping.account_code,
        "account_name": mapping.account_name,
        "debit": float(amount if debit else 0),
        "credit": float(0 if debit else amount),
        "narration": narration,
        "_document_key": f"{document_type}:{document_no}",
    })


def build_journal(session: Session, start: date, end: date) -> list[dict]:
    if start > end:
        raise AccountingExportError("Start date must be on or before end date.")
    mappings = _mapping_map(session)
    rows: list[dict] = []
    invoices = session.scalars(
        select(SalesInvoice).where(
            SalesInvoice.status.in_(["ISSUED", "PARTIALLY_PAID", "PAID"]),
            SalesInvoice.issued_at >= datetime.combine(start, time.min),
            SalesInvoice.issued_at <= datetime.combine(end, time.max),
        )
    ).all()
    for invoice in invoices:
        narration = f"Sales invoice {invoice.invoice_no}"
        common = dict(document_type="INVOICE", document_no=invoice.invoice_no,
                      occurred_at=invoice.issued_at or invoice.invoice_date, narration=narration)
        _add_line(rows, mappings, mapping_key="ACCOUNTS_RECEIVABLE", amount=invoice.total,
                  debit=True, **common)
        _add_line(rows, mappings, mapping_key="SALES_REVENUE", amount=invoice.taxable_total,
                  debit=False, **common)
        for key, amount in (
            ("OUTPUT_CGST", invoice.cgst_total), ("OUTPUT_SGST", invoice.sgst_total),
            ("OUTPUT_IGST", invoice.igst_total), ("OUTPUT_CESS", invoice.cess_total),
        ):
            _add_line(rows, mappings, mapping_key=key, amount=amount, debit=False, **common)

    payments = session.scalars(
        select(Payment).where(
            Payment.status == "RECONCILED",
            Payment.payment_date >= datetime.combine(start, time.min),
            Payment.payment_date <= datetime.combine(end, time.max),
        )
    ).all()
    for payment in payments:
        allocations = list(session.scalars(
            select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
        ))
        for allocation in allocations:
            invoice = session.get(SalesInvoice, allocation.invoice_id)
            mapping_key = payment.method if payment.method in DEFAULT_MAPPINGS else "OTHER"
            common = dict(
                document_type="RECEIPT", document_no=payment.receipt_no,
                occurred_at=payment.payment_date,
                narration=f"Receipt {payment.receipt_no} allocated to {invoice.invoice_no}",
            )
            _add_line(rows, mappings, mapping_key=mapping_key, amount=allocation.amount,
                      debit=True, **common)
            _add_line(rows, mappings, mapping_key="ACCOUNTS_RECEIVABLE", amount=allocation.amount,
                      debit=False, **common)

    notes = session.scalars(
        select(CreditNote).where(
            CreditNote.status == "ISSUED",
            CreditNote.issued_at >= datetime.combine(start, time.min),
            CreditNote.issued_at <= datetime.combine(end, time.max),
        )
    ).all()
    for note in notes:
        narration = f"Credit note {note.note_no}"
        common = dict(document_type="DEBIT_NOTE" if note.note_type == "DEBIT" else "CREDIT_NOTE",
                  document_no=note.note_no,
                      occurred_at=note.issued_at or note.created_at, narration=narration)
        if note.note_type == "DEBIT":
            _add_line(rows, mappings, mapping_key="ACCOUNTS_RECEIVABLE", amount=note.total,
                      debit=True, **common)
            _add_line(rows, mappings, mapping_key="SALES_REVENUE", amount=note.taxable_total,
                      debit=False, **common)
            for key, amount in (
                ("OUTPUT_CGST", note.cgst_total), ("OUTPUT_SGST", note.sgst_total),
                ("OUTPUT_IGST", note.igst_total), ("OUTPUT_CESS", note.cess_total),
            ):
                _add_line(rows, mappings, mapping_key=key, amount=amount, debit=False, **common)
        else:
            _add_line(rows, mappings, mapping_key="SALES_RETURNS", amount=note.taxable_total,
                      debit=True, **common)
            for key, amount in (
                ("OUTPUT_CGST", note.cgst_total), ("OUTPUT_SGST", note.sgst_total),
                ("OUTPUT_IGST", note.igst_total), ("OUTPUT_CESS", note.cess_total),
            ):
                _add_line(rows, mappings, mapping_key=key, amount=amount, debit=True, **common)
            _add_line(rows, mappings, mapping_key="ACCOUNTS_RECEIVABLE", amount=note.total,
                      debit=False, **common)

    balances: dict[str, tuple[Decimal, Decimal]] = {}
    for row in rows:
        key = row["_document_key"]
        debit, credit = balances.get(key, (Decimal("0"), Decimal("0")))
        balances[key] = (debit + Decimal(str(row["debit"])), credit + Decimal(str(row["credit"])))
    unbalanced = {key: pair for key, pair in balances.items() if money(pair[0]) != money(pair[1])}
    if unbalanced:
        raise AccountingExportError(f"Journal is unbalanced: {unbalanced}")
    for row in rows:
        row.pop("_document_key", None)
    return rows


def create_export(
    session: Session,
    *,
    actor_id: int,
    start: date,
    end: date,
) -> tuple[AccountingExport, str]:
    actor = _actor(session, actor_id)
    rows = build_journal(session, start, end)
    filename = f"krypton-journal-{start:%Y%m%d}-{end:%Y%m%d}.csv"
    buffer = io.StringIO(newline="")
    columns = ["date", "document_type", "document_no", "account_code", "account_name", "debit", "credit", "narration"]
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    export = AccountingExport(
        export_no=f"EXP-{datetime.now():%Y%m%d}-{secrets.token_hex(3).upper()}",
        date_from=datetime.combine(start, time.min),
        date_to=datetime.combine(end, time.max),
        status="GENERATED",
        file_name=filename,
        row_count=len(rows),
        exported_by_id=actor.id,
    )
    session.add(export)
    session.flush()
    audit.record(
        session, actor_id=actor.id, action="EXPORT", entity_type="ACCOUNTING_EXPORT",
        entity_id=export.id, changes={"from": start, "to": end, "rows": len(rows)},
    )
    return export, buffer.getvalue()


def list_exports(session: Session) -> list[AccountingExport]:
    return list(session.scalars(select(AccountingExport).order_by(AccountingExport.exported_at.desc())))
