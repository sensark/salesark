from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.models import Payment, PaymentAllocation, SalesInvoice, User
from erp.permissions import require_action
from erp.services import audit
from erp.services.documents import next_document_number
from erp.services.discounts import money


class PaymentError(ValueError):
    pass


PAYMENT_METHODS = ("CASH", "BANK_TRANSFER", "UPI", "CHEQUE", "CARD", "OTHER")


def _require_accounts(session: Session, actor_id: int, action: str) -> User:
    actor = session.get(User, actor_id)
    if actor is None:
        raise PaymentError("User not found.")
    try:
        require_action(actor.role, action)
    except PermissionError as exc:
        raise PaymentError(str(exc)) from exc
    return actor


def create_payment(
    session: Session,
    *,
    customer_id: int,
    actor_id: int,
    amount: Decimal,
    method: str,
    reference: str = "",
    notes: str = "",
) -> Payment:
    actor = _require_accounts(session, actor_id, "payment.create")
    amount = money(amount)
    method = method.upper()
    if amount <= 0:
        raise PaymentError("Payment amount must be greater than zero.")
    if method not in PAYMENT_METHODS:
        raise PaymentError("Choose a supported payment method.")
    payment = Payment(
        receipt_no=next_document_number(session, "PAYMENT"),
        customer_id=customer_id,
        amount=amount,
        method=method,
        reference=reference.strip() or None,
        notes=notes.strip() or None,
        status="UNRECONCILED",
        created_by_id=actor.id,
    )
    session.add(payment)
    session.flush()
    audit.record(
        session, actor_id=actor.id, action="CREATE", entity_type="PAYMENT",
        entity_id=payment.id, changes={"amount": amount, "method": method},
    )
    return payment


def allocated_amount(session: Session, payment_id: int) -> Decimal:
    return session.scalar(
        select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
            PaymentAllocation.payment_id == payment_id
        )
    ) or Decimal("0")


def allocate_payment(
    session: Session,
    *,
    payment_id: int,
    actor_id: int,
    allocations: dict[int, Decimal],
) -> Payment:
    actor = _require_accounts(session, actor_id, "payment.allocate")
    payment = session.get(Payment, payment_id)
    if payment is None:
        raise PaymentError("Payment receipt not found.")
    if payment.status == "VOID":
        raise PaymentError("A voided receipt cannot be allocated.")
    cleaned = {invoice_id: money(amount) for invoice_id, amount in allocations.items()}
    if not cleaned or any(amount <= 0 for amount in cleaned.values()):
        raise PaymentError("Enter positive allocations for at least one invoice.")
    if sum(cleaned.values(), Decimal("0")) > payment.amount - allocated_amount(session, payment_id):
        raise PaymentError("Allocations exceed the unallocated receipt amount.")

    for invoice_id, amount in cleaned.items():
        invoice = session.get(SalesInvoice, invoice_id)
        if invoice is None or invoice.customer_id != payment.customer_id:
            raise PaymentError("The invoice does not belong to this customer.")
        if invoice.status not in {"ISSUED", "PARTIALLY_PAID"}:
            raise PaymentError("Only issued, unpaid invoices can receive allocations.")
        if amount > invoice.balance_due:
            raise PaymentError(f"Allocation exceeds the balance due on {invoice.invoice_no}.")
        allocation = session.scalar(
            select(PaymentAllocation).where(
                PaymentAllocation.payment_id == payment_id,
                PaymentAllocation.invoice_id == invoice_id,
            )
        )
        if allocation:
            allocation.amount = money(allocation.amount + amount)
        else:
            session.add(PaymentAllocation(payment_id=payment_id, invoice_id=invoice_id, amount=amount))
        invoice.amount_paid = money(invoice.amount_paid + amount)
        invoice.balance_due = money(invoice.balance_due - amount)
        invoice.status = "PAID" if invoice.balance_due == 0 else "PARTIALLY_PAID"
        audit.record(
            session, actor_id=actor.id, action="ALLOCATE", entity_type="INVOICE",
            entity_id=invoice.id, changes={"payment_id": payment.id, "amount": amount,
                                           "balance_due": invoice.balance_due},
        )
    session.flush()
    audit.record(
        session, actor_id=actor.id, action="ALLOCATE", entity_type="PAYMENT",
        entity_id=payment.id, changes={"allocations": cleaned},
    )
    return payment


def reconcile_payment(session: Session, payment_id: int, actor_id: int) -> Payment:
    actor = _require_accounts(session, actor_id, "payment.reconcile")
    payment = session.get(Payment, payment_id)
    if payment is None or payment.status == "VOID":
        raise PaymentError("Payment receipt cannot be reconciled.")
    payment.status = "RECONCILED"
    audit.record(
        session, actor_id=actor.id, action="RECONCILE", entity_type="PAYMENT",
        entity_id=payment.id, changes={"status": payment.status},
    )
    return payment


def list_payments(session: Session) -> list[Payment]:
    return list(session.scalars(select(Payment).order_by(Payment.payment_date.desc())))
