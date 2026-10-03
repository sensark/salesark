from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from erp.models import (
    STATUS_PENDING,
    Customer,
    Order,
    OrderItem,
    Quotation,
    QuotationItem,
    User,
)
from erp.permissions import require_action
from erp.services import audit, notifications
from erp.services.documents import next_document_number
from erp.services.discounts import money
from erp.services.orders import CartLine, OrderError, approval_requirement, price_cart


class QuotationError(ValueError):
    pass


def create_quotation(
    session: Session,
    *,
    customer_id: int,
    sales_person_id: int,
    lines: list[CartLine],
    valid_days: int = 30,
    notes: str = "",
    terms: str = "",
) -> Quotation:
    actor = session.get(User, sales_person_id)
    customer = session.get(Customer, customer_id)
    if actor is None or customer is None or customer.customer_status != "ACTIVE":
        raise QuotationError("An active customer and sales user are required.")
    try:
        require_action(actor.role, "quotation.create")
        priced = price_cart(session, lines, customer_id=customer.id)
    except (PermissionError, OrderError, ValueError) as exc:
        raise QuotationError(str(exc)) from exc

    quotation = Quotation(
        quotation_no=next_document_number(session, "QUOTATION"),
        customer_id=customer.id,
        sales_person_id=actor.id,
        status="DRAFT",
        currency="INR",
        subtotal=money(sum((item.gross for item in priced), Decimal("0"))),
        discount_total=money(sum((item.tax.discount for item in priced), Decimal("0"))),
        taxable_total=money(sum((item.tax.taxable for item in priced), Decimal("0"))),
        cgst_total=money(sum((item.tax.cgst for item in priced), Decimal("0"))),
        sgst_total=money(sum((item.tax.sgst for item in priced), Decimal("0"))),
        igst_total=money(sum((item.tax.igst for item in priced), Decimal("0"))),
        cess_total=money(sum((item.tax.cess for item in priced), Decimal("0"))),
        tax_total=money(sum((item.tax.total_tax for item in priced), Decimal("0"))),
        total=money(sum((item.tax.total for item in priced), Decimal("0"))),
        valid_until=datetime.now() + timedelta(days=max(1, valid_days)),
        notes=notes.strip() or None,
        terms=terms.strip() or None,
        billing_address_snapshot=customer.address,
        shipping_address_snapshot=customer.address,
        items=[
            QuotationItem(
                product_id=item.product.id,
                description=item.product.name,
                hsn_sac=item.product.hsn_sac,
                qty=item.qty,
                unit_price=item.unit_price,
                discount_pct=item.discount_pct,
                gst_rate=item.tax.cgst_rate + item.tax.sgst_rate + item.tax.igst_rate,
                cess_rate=item.tax.cess_rate,
                taxable_amount=item.tax.taxable,
                cgst_amount=item.tax.cgst,
                sgst_amount=item.tax.sgst,
                igst_amount=item.tax.igst,
                cess_amount=item.tax.cess,
                line_total=item.tax.total,
            )
            for item in priced
        ],
    )
    session.add(quotation)
    session.flush()
    return quotation


def list_quotations(session: Session, *, sales_person_id: int | None = None) -> list[Quotation]:
    expire_due(session)
    stmt = (
        select(Quotation)
        .options(selectinload(Quotation.items))
        .order_by(Quotation.created_at.desc())
    )
    if sales_person_id is not None:
        stmt = stmt.where(Quotation.sales_person_id == sales_person_id)
    return list(session.scalars(stmt))


def expire_due(session: Session, now: datetime | None = None) -> int:
    now = now or datetime.now()
    due = session.scalars(
        select(Quotation).where(
            Quotation.status.in_(["DRAFT", "SUBMITTED", "APPROVED", "SENT"]),
            Quotation.valid_until < now,
        )
    ).all()
    for quote in due:
        quote.status = "EXPIRED"
        audit.record(
            session, actor_id=None, action="EXPIRE", entity_type="QUOTATION",
            entity_id=quote.id, changes={"status": "EXPIRED"},
        )
    return len(due)


def transition(
    session: Session,
    quotation_id: int,
    actor_id: int,
    action: str,
    reason: str = "",
) -> Quotation:
    quote = session.get(Quotation, quotation_id)
    actor = session.get(User, actor_id)
    if quote is None or actor is None:
        raise QuotationError("Quotation or user not found.")
    permission = {
        "submit": "quotation.create",
        "approve": "quotation.approve",
        "send": "quotation.send",
        "accept": "quotation.accept",
        "reject": "quotation.approve",
        "cancel": "quotation.create",
    }.get(action)
    if permission is None:
        raise QuotationError("Unsupported quotation action.")
    try:
        require_action(actor.role, permission)
    except PermissionError as exc:
        raise QuotationError(str(exc)) from exc

    transitions = {
        ("DRAFT", "submit"): "SUBMITTED",
        ("SUBMITTED", "approve"): "APPROVED",
        ("APPROVED", "send"): "SENT",
        ("SENT", "accept"): "ACCEPTED",
        ("SUBMITTED", "reject"): "REJECTED",
        ("APPROVED", "reject"): "REJECTED",
        ("SENT", "reject"): "REJECTED",
        ("DRAFT", "cancel"): "CANCELLED",
        ("SUBMITTED", "cancel"): "CANCELLED",
        ("APPROVED", "cancel"): "CANCELLED",
        ("SENT", "cancel"): "CANCELLED",
    }
    target = transitions.get((quote.status, action))
    if target is None:
        raise QuotationError(f"Cannot {action} a quotation in {quote.status.lower()} status.")
    if (
        action in {"submit", "approve", "send", "accept"}
        and quote.valid_until is not None
        and quote.valid_until < datetime.now()
    ):
        raise QuotationError("This quotation has expired and cannot continue through the workflow.")
    if action == "reject" and not reason.strip():
        raise QuotationError("A rejection reason is required.")
    now = datetime.now()
    quote.status = target
    quote.rejection_reason = reason.strip() if action == "reject" else None
    if action in {"approve", "reject"}:
        quote.decided_by_id = actor.id
        quote.decided_at = now
    if action == "send":
        quote.sent_at = now
    if action == "accept":
        quote.accepted_at = now
    session.flush()
    audit.record(
        session, actor_id=actor.id, action=action.upper(), entity_type="QUOTATION",
        entity_id=quote.id,
        changes={"status": quote.status, "reason": quote.rejection_reason},
    )
    return quote


def convert_to_order(session: Session, quotation_id: int, actor_id: int) -> Order:
    quote = session.get(Quotation, quotation_id)
    actor = session.get(User, actor_id)
    if quote is None or actor is None:
        raise QuotationError("Quotation or user not found.")
    try:
        require_action(actor.role, "quotation.convert")
    except PermissionError as exc:
        raise QuotationError(str(exc)) from exc
    if quote.status != "ACCEPTED":
        raise QuotationError("Only accepted quotations can be converted.")
    if quote.converted_order_id:
        existing = session.get(Order, quote.converted_order_id)
        if existing:
            return existing
        raise QuotationError("Quotation conversion reference is inconsistent.")
    customer = session.get(Customer, quote.customer_id)
    if customer is None or customer.customer_status != "ACTIVE":
        raise QuotationError("Customer is not active.")
    credit_exceeded, approver_role = approval_requirement(
        session, customer=customer, total=quote.total,
        discount_pct=(quote.discount_total * Decimal("100") / quote.subtotal)
        if quote.subtotal else Decimal("0"),
    )

    order = Order(
        order_no=next_document_number(session, "ORDER"),
        customer_id=quote.customer_id,
        sales_person_id=quote.sales_person_id,
        status=STATUS_PENDING,
        credit_limit_exceeded=credit_exceeded,
        required_approver_role=approver_role,
        subtotal=quote.subtotal,
        discount_total=quote.discount_total,
        taxable_total=quote.taxable_total,
        cgst_total=quote.cgst_total,
        sgst_total=quote.sgst_total,
        igst_total=quote.igst_total,
        cess_total=quote.cess_total,
        tax_total=quote.tax_total,
        total=quote.total,
        currency=quote.currency,
        notes=quote.notes,
        source_quotation_id=quote.id,
        billing_address_snapshot=quote.billing_address_snapshot,
        shipping_address_snapshot=quote.shipping_address_snapshot,
        items=[
            OrderItem(
                product_id=item.product_id,
                qty=item.qty,
                unit_price=item.unit_price,
                discount_pct=item.discount_pct,
                hsn_sac=item.hsn_sac,
                gst_rate=item.gst_rate,
                cess_rate=item.cess_rate,
                taxable_amount=item.taxable_amount,
                cgst_amount=item.cgst_amount,
                sgst_amount=item.sgst_amount,
                igst_amount=item.igst_amount,
                cess_amount=item.cess_amount,
                line_total=item.taxable_amount,
            )
            for item in session.scalars(
                select(QuotationItem).where(QuotationItem.quotation_id == quote.id)
            )
        ],
    )
    session.add(order)
    session.flush()
    quote.converted_order_id = order.id
    audit.record(
        session, actor_id=actor.id, action="CONVERT", entity_type="QUOTATION",
        entity_id=quote.id, changes={"order_id": order.id},
    )
    notifications.notify_approvers(
        session,
        approver_role,
        f"Accepted quotation {quote.quotation_no} converted to order {order.order_no}.",
        order.id,
    )
    return order
