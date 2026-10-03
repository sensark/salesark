from datetime import datetime
from decimal import Decimal

import pytest

from erp.models import (
    CreditNote, Payment, PaymentAllocation, SalesInvoice,
)
from erp.services import accounting_export
from erp.services.accounting_export import AccountingExportError


def _mappings(session, admin_id):
    for key, (code, name) in accounting_export.DEFAULT_MAPPINGS.items():
        accounting_export.save_mapping(session, actor_id=admin_id, mapping_key=key,
                                       account_code=code, account_name=name)


def test_journal_balances_invoice_receipt_and_credit_note(session, data):
    _mappings(session, data["admin"].id)
    now = datetime.now()
    invoice = SalesInvoice(
        invoice_no="INV-TEST", customer_id=data["customer"].id, order_id=1, status="ISSUED",
        invoice_date=now, issued_at=now, subtotal=Decimal("100"), discount_total=Decimal("0"),
        taxable_total=Decimal("100"), cgst_total=Decimal("9"), sgst_total=Decimal("9"),
        igst_total=Decimal("0"), cess_total=Decimal("0"), tax_total=Decimal("18"),
        charges_total=Decimal("0"), round_off=Decimal("0"), total=Decimal("118"),
        amount_paid=Decimal("20"), credit_total=Decimal("0"), balance_due=Decimal("98"),
        created_by_id=data["admin"].id,
    )
    session.add(invoice)
    session.flush()
    receipt = Payment(
        receipt_no="RCPT-TEST", customer_id=data["customer"].id, amount=Decimal("20"),
        method="UPI", status="RECONCILED", created_by_id=data["admin"].id,
    )
    session.add(receipt)
    session.flush()
    session.add(PaymentAllocation(payment_id=receipt.id, invoice_id=invoice.id, amount=Decimal("20")))
    note = CreditNote(
        note_no="CN-TEST", note_type="CREDIT", customer_id=data["customer"].id,
        invoice_id=invoice.id, status="ISSUED", reason="DAMAGED", subtotal=Decimal("10"),
        taxable_total=Decimal("10"), cgst_total=Decimal(".90"), sgst_total=Decimal(".90"),
        igst_total=Decimal("0"), cess_total=Decimal("0"), total=Decimal("11.80"),
        issued_at=now, created_by_id=data["admin"].id,
    )
    session.add(note)
    session.flush()

    rows = accounting_export.build_journal(session, now.date(), now.date())
    totals = {}
    for row in rows:
        key = (row["document_type"], row["document_no"])
        debit, credit = totals.get(key, (Decimal("0"), Decimal("0")))
        totals[key] = debit + Decimal(str(row["debit"])), credit + Decimal(str(row["credit"]))
    assert set(totals) == {("INVOICE", "INV-TEST"), ("RECEIPT", "RCPT-TEST"), ("CREDIT_NOTE", "CN-TEST")}
    assert all(debit == credit for debit, credit in totals.values())


def test_journal_requires_account_mappings_and_balances(session, data):
    now = datetime.now()
    session.add(SalesInvoice(
        invoice_no="INV-NO-MAP", customer_id=data["customer"].id, order_id=1,
        status="ISSUED", invoice_date=now, issued_at=now,
        subtotal=Decimal("100"), discount_total=Decimal("0"), taxable_total=Decimal("100"),
        cgst_total=Decimal("0"), sgst_total=Decimal("0"), igst_total=Decimal("0"),
        cess_total=Decimal("0"), tax_total=Decimal("0"), charges_total=Decimal("0"),
        round_off=Decimal("0"), total=Decimal("100"), amount_paid=Decimal("0"),
        credit_total=Decimal("0"), balance_due=Decimal("100"), created_by_id=data["admin"].id,
    ))
    session.flush()
    with pytest.raises(AccountingExportError):
        accounting_export.build_journal(session, now.date(), now.date())


def test_non_accounts_cannot_export(session, data):
    with pytest.raises(AccountingExportError):
        accounting_export.create_export(session, actor_id=data["sales"].id,
                                        start=datetime.now().date(), end=datetime.now().date())
