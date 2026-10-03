from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp import config
from erp.models import (
    CreditNote,
    CreditNoteItem,
    Customer,
    InvoiceItem,
    SalesInvoice,
    SalesReturn,
    SalesReturnItem,
    User,
)
from erp.permissions import require_action
from erp.services import audit, inventory
from erp.services.documents import next_document_number
from erp.services.discounts import money
from erp.services.tax import calculate_gst


class ReturnError(ValueError):
    pass


REASONS = ("DAMAGED", "WRONG_PRODUCT", "EXCESS_QUANTITY", "CANCELLATION", "QUALITY", "OTHER")


def _actor(session: Session, actor_id: int, action: str) -> User:
    actor = session.get(User, actor_id)
    if actor is None:
        raise ReturnError("User not found.")
    try:
        require_action(actor.role, action)
    except PermissionError as exc:
        raise ReturnError(str(exc)) from exc
    return actor


def _qty_already_returned(session: Session, invoice_item_id: int) -> int:
    return session.scalar(
        select(func.coalesce(func.sum(SalesReturnItem.qty), 0))
        .join(SalesReturn, SalesReturn.id == SalesReturnItem.return_id)
        .where(
            SalesReturnItem.invoice_item_id == invoice_item_id,
            SalesReturn.status.notin_(["REJECTED", "CANCELLED"]),
        )
    ) or 0


def create_return(
    session: Session,
    *,
    invoice_id: int,
    actor_id: int,
    quantities: dict[int, int],
    reason: str,
    notes: str = "",
    restock: bool = True,
) -> SalesReturn:
    actor = _actor(session, actor_id, "return.create")
    invoice = session.get(SalesInvoice, invoice_id)
    reason = reason.upper()
    if invoice is None or invoice.status not in {"ISSUED", "PARTIALLY_PAID", "PAID"}:
        raise ReturnError("Returns must reference an issued invoice.")
    if reason not in REASONS:
        raise ReturnError("Choose a valid return reason.")
    if not quantities or any(qty <= 0 for qty in quantities.values()):
        raise ReturnError("Enter positive return quantities.")
    item_map = {item.id: item for item in session.scalars(
        select(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id)
    )}
    for item_id, qty in quantities.items():
        item = item_map.get(item_id)
        if item is None or qty + _qty_already_returned(session, item_id) > item.qty:
            raise ReturnError("Return quantity exceeds the quantity invoiced and not already returned.")

    sales_return = SalesReturn(
        return_no=next_document_number(session, "RETURN"),
        customer_id=invoice.customer_id,
        invoice_id=invoice.id,
        status="REQUESTED",
        reason=reason,
        notes=notes.strip() or None,
        requested_by_id=actor.id,
        items=[SalesReturnItem(invoice_item_id=item_id, qty=qty, restock=restock)
               for item_id, qty in quantities.items()],
    )
    session.add(sales_return)
    session.flush()
    audit.record(
        session, actor_id=actor.id, action="CREATE", entity_type="SALES_RETURN",
        entity_id=sales_return.id, changes={"reason": reason, "quantities": quantities},
    )
    return sales_return


def decide_return(
    session: Session,
    return_id: int,
    actor_id: int,
    *,
    approve: bool,
    reason: str = "",
) -> SalesReturn:
    actor = _actor(session, actor_id, "return.approve")
    sales_return = session.get(SalesReturn, return_id)
    if sales_return is None or sales_return.status != "REQUESTED":
        raise ReturnError("Only requested returns can be decided.")
    if not approve and not reason.strip():
        raise ReturnError("A rejection reason is required.")
    sales_return.status = "APPROVED" if approve else "REJECTED"
    sales_return.decided_by_id = actor.id
    sales_return.decided_at = datetime.now()
    if not approve:
        sales_return.notes = f"{sales_return.notes or ''}\nRejected: {reason.strip()}".strip()
    audit.record(
        session, actor_id=actor.id, action="APPROVE" if approve else "REJECT",
        entity_type="SALES_RETURN", entity_id=sales_return.id,
        changes={"status": sales_return.status, "reason": reason.strip()},
    )
    return sales_return


def receive_return(session: Session, return_id: int, actor_id: int) -> SalesReturn:
    actor = _actor(session, actor_id, "return.receive")
    sales_return = session.get(SalesReturn, return_id)
    if sales_return is None or sales_return.status != "APPROVED":
        raise ReturnError("Only approved returns can be received.")
    for item in sales_return.items:
        if item.restock:
            invoice_item = session.get(InvoiceItem, item.invoice_item_id)
            inventory.record_movement(
                session,
                product_id=invoice_item.product_id,
                qty_delta=item.qty,
                source_type="SALES_RETURN",
                source_id=sales_return.id,
                source_line_id=item.id,
                actor_id=actor.id,
                reason=f"Received return {sales_return.return_no}",
            )
    sales_return.status = "RECEIVED"
    sales_return.received_at = datetime.now()
    audit.record(
        session, actor_id=actor.id, action="RECEIVE", entity_type="SALES_RETURN",
        entity_id=sales_return.id, changes={"status": "RECEIVED"},
    )
    return sales_return


def create_credit_note(session: Session, return_id: int, actor_id: int) -> CreditNote:
    actor = _actor(session, actor_id, "credit_note.create")
    sales_return = session.get(SalesReturn, return_id)
    if sales_return is None or sales_return.status != "RECEIVED":
        raise ReturnError("A credit note requires a received return.")
    existing = session.scalar(select(CreditNote).where(CreditNote.return_id == return_id))
    if existing:
        return existing
    invoice = session.get(SalesInvoice, sales_return.invoice_id)
    customer = session.get(Customer, sales_return.customer_id)
    if invoice is None or customer is None:
        raise ReturnError("Linked invoice or customer was not found.")

    items = []
    for returned in sales_return.items:
        invoice_item = session.get(InvoiceItem, returned.invoice_item_id)
        tax = calculate_gst(
            unit_price=invoice_item.unit_price,
            qty=returned.qty,
            discount_pct=invoice_item.discount_pct,
            gst_rate=invoice_item.gst_rate,
            cess_rate=invoice_item.cess_rate,
            supplier_state=config.COMPANY_STATE,
            place_of_supply_state=invoice.place_of_supply_state or config.COMPANY_STATE,
            supply_type="EXPORT" if customer.country_code.upper() != "IN" else "DOMESTIC",
        )
        items.append((invoice_item, returned.qty, tax))

    subtotal = sum((tax.gross for _, _, tax in items), Decimal("0"))
    taxable = sum((tax.taxable for _, _, tax in items), Decimal("0"))
    cgst = sum((tax.cgst for _, _, tax in items), Decimal("0"))
    sgst = sum((tax.sgst for _, _, tax in items), Decimal("0"))
    igst = sum((tax.igst for _, _, tax in items), Decimal("0"))
    cess = sum((tax.cess for _, _, tax in items), Decimal("0"))
    total = taxable + cgst + sgst + igst + cess
    note = CreditNote(
        note_no=next_document_number(session, "CREDIT_NOTE"),
        note_type="CREDIT",
        customer_id=customer.id,
        invoice_id=invoice.id,
        return_id=sales_return.id,
        status="DRAFT",
        reason=sales_return.reason,
        subtotal=money(subtotal),
        taxable_total=money(taxable),
        cgst_total=money(cgst),
        sgst_total=money(sgst),
        igst_total=money(igst),
        cess_total=money(cess),
        total=money(total),
        created_by_id=actor.id,
        items=[
            CreditNoteItem(
                invoice_item_id=line.id,
                qty=qty,
                taxable_amount=tax.taxable,
                cgst_amount=tax.cgst,
                sgst_amount=tax.sgst,
                igst_amount=tax.igst,
                cess_amount=tax.cess,
                line_total=tax.total,
            )
            for line, qty, tax in items
        ],
    )
    session.add(note)
    session.flush()
    audit.record(
        session, actor_id=actor.id, action="CREATE", entity_type="CREDIT_NOTE",
        entity_id=note.id, changes={"total": note.total, "return_id": sales_return.id},
    )
    return note


def issue_credit_note(session: Session, note_id: int, actor_id: int) -> CreditNote:
    actor = _actor(session, actor_id, "credit_note.issue")
    note = session.get(CreditNote, note_id)
    if note is None or note.status != "DRAFT":
        raise ReturnError("Only draft credit notes can be issued.")
    invoice = session.get(SalesInvoice, note.invoice_id)
    if note.note_type == "CREDIT" and invoice.credit_total + note.total > invoice.total + invoice.debit_total:
        raise ReturnError("Credit note exceeds the invoice value after prior credit notes.")
    note.status = "ISSUED"
    note.issued_at = datetime.now()
    note.issued_by_id = actor.id
    if note.note_type == "DEBIT":
        invoice.debit_total = money(invoice.debit_total + note.total)
    else:
        invoice.credit_total = money(invoice.credit_total + note.total)
    invoice.balance_due = max(
        Decimal("0"),
        money(invoice.total + invoice.debit_total - invoice.amount_paid - invoice.credit_total),
    )
    if invoice.balance_due == 0:
        invoice.status = "PAID"
    elif invoice.amount_paid or invoice.credit_total:
        invoice.status = "PARTIALLY_PAID"
    else:
        invoice.status = "ISSUED"
    audit.record(
        session, actor_id=actor.id, action="ISSUE", entity_type="CREDIT_NOTE",
        entity_id=note.id, changes={"status": "ISSUED", "total": note.total},
    )
    return note


def create_debit_note(
    session: Session,
    *,
    invoice_id: int,
    invoice_item_id: int,
    actor_id: int,
    taxable_amount: Decimal,
    reason: str,
) -> CreditNote:
    actor = _actor(session, actor_id, "credit_note.create")
    invoice = session.get(SalesInvoice, invoice_id)
    line = session.get(InvoiceItem, invoice_item_id)
    reason = reason.strip()
    taxable_amount = money(taxable_amount)
    if invoice is None or line is None or line.invoice_id != invoice_id:
        raise ReturnError("Choose an invoice line for this debit note.")
    if invoice.status not in {"ISSUED", "PARTIALLY_PAID", "PAID"}:
        raise ReturnError("Debit notes require an issued invoice.")
    if taxable_amount <= 0 or not reason:
        raise ReturnError("A positive taxable amount and reason are required.")
    customer = session.get(Customer, invoice.customer_id)
    gst_rate = line.gst_rate
    cess_rate = line.cess_rate
    tax = calculate_gst(
        unit_price=taxable_amount,
        qty=1,
        gst_rate=gst_rate,
        cess_rate=cess_rate,
        supplier_state=config.COMPANY_STATE,
        place_of_supply_state=invoice.place_of_supply_state or config.COMPANY_STATE,
        supply_type="EXPORT" if customer.country_code.upper() != "IN" else "DOMESTIC",
    )
    note = CreditNote(
        note_no=next_document_number(session, "DEBIT_NOTE"),
        note_type="DEBIT",
        customer_id=customer.id,
        invoice_id=invoice.id,
        status="DRAFT",
        reason=reason,
        subtotal=tax.gross,
        taxable_total=tax.taxable,
        cgst_total=tax.cgst,
        sgst_total=tax.sgst,
        igst_total=tax.igst,
        cess_total=tax.cess,
        total=tax.total,
        created_by_id=actor.id,
        items=[CreditNoteItem(
            invoice_item_id=line.id, qty=1, taxable_amount=tax.taxable,
            cgst_amount=tax.cgst, sgst_amount=tax.sgst,
            igst_amount=tax.igst, cess_amount=tax.cess, line_total=tax.total,
        )],
    )
    session.add(note)
    session.flush()
    audit.record(
        session, actor_id=actor.id, action="CREATE", entity_type="DEBIT_NOTE",
        entity_id=note.id, changes={"invoice_id": invoice.id, "total": note.total, "reason": reason},
    )
    return note


def list_returns(session: Session) -> list[SalesReturn]:
    return list(session.scalars(select(SalesReturn).order_by(SalesReturn.created_at.desc())))


def list_credit_notes(session: Session) -> list[CreditNote]:
    return list(session.scalars(select(CreditNote).order_by(CreditNote.created_at.desc())))
