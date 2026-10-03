from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp import config
from erp.models import (
    Delivery,
    DeliveryItem,
    InvoiceItem,
    SalesInvoice,
    Customer,
    Order,
    OrderItem,
    STATUS_APPROVED,
    User,
)
from erp.permissions import require_action
from erp.services import audit
from erp.services.documents import next_document_number
from erp.services.discounts import money
from erp.services.tax import calculate_gst


class InvoiceError(ValueError):
    pass


ISSUABLE_INVOICE_STATUSES = ("ISSUED", "PARTIALLY_PAID", "PAID")


def _require_accounts(session: Session, actor_id: int, action: str) -> User:
    actor = session.get(User, actor_id)
    if actor is None:
        raise InvoiceError("User not found.")
    try:
        require_action(actor.role, action)
    except PermissionError as exc:
        raise InvoiceError(str(exc)) from exc
    return actor


def unbilled_quantities(session: Session, delivery_id: int) -> dict[int, int]:
    delivery = session.get(Delivery, delivery_id)
    if delivery is None or delivery.status != "CONFIRMED":
        return {}
    rows = session.execute(
        select(InvoiceItem.delivery_item_id, func.coalesce(func.sum(InvoiceItem.qty), 0))
        .join(SalesInvoice, SalesInvoice.id == InvoiceItem.invoice_id)
        .where(
            InvoiceItem.delivery_item_id.in_(
                select(DeliveryItem.id).where(DeliveryItem.delivery_id == delivery_id)
            ),
            SalesInvoice.status != "CANCELLED",
        )
        .group_by(InvoiceItem.delivery_item_id)
    )
    already_invoiced = {delivery_item_id: int(qty) for delivery_item_id, qty in rows}
    items = session.scalars(select(DeliveryItem).where(DeliveryItem.delivery_id == delivery_id)).all()
    return {item.id: item.qty - already_invoiced.get(item.id, 0) for item in items}


def list_invoiceable_deliveries(session: Session) -> list[Delivery]:
    deliveries = session.scalars(
        select(Delivery).where(Delivery.status == "CONFIRMED").order_by(Delivery.confirmed_at)
    ).all()
    return [
        delivery for delivery in deliveries
        if any(unbilled_quantities(session, delivery.id).values())
        and not session.scalar(select(SalesInvoice.id).where(
            SalesInvoice.order_id == delivery.order_id,
            SalesInvoice.status != "CANCELLED",
        ))
    ]


def create_order_invoice(
    session: Session,
    *,
    order_id: int,
    actor_id: int,
    invoice_date: datetime | None = None,
) -> SalesInvoice:
    actor = session.get(User, actor_id)
    order = session.get(Order, order_id)
    if actor is None or order is None or order.status != STATUS_APPROVED:
        raise InvoiceError(
            "An order invoice requires an approved order and valid approver."
        )
    try:
        require_action(actor.role, "order.approve")
    except PermissionError as exc:
        raise InvoiceError(str(exc)) from exc
    existing = session.scalar(select(SalesInvoice).where(
        SalesInvoice.order_id == order.id, SalesInvoice.status != "CANCELLED",
    ))
    if existing:
        return existing
    customer = session.get(Customer, order.customer_id)
    if customer is None or not order.items:
        raise InvoiceError(
            "The approved order has no invoiceable customer or items."
        )
    invoice_date = invoice_date or datetime.now()
    invoice_items = [
        InvoiceItem(
            order_item_id=line.id,
            product_id=line.product_id,
            description=line.product.name,
            hsn_sac=line.hsn_sac,
            qty=line.qty,
            unit_price=line.unit_price,
            discount_pct=line.discount_pct,
            gst_rate=line.gst_rate,
            cess_rate=line.cess_rate,
            taxable_amount=line.taxable_amount,
            cgst_amount=line.cgst_amount,
            sgst_amount=line.sgst_amount,
            igst_amount=line.igst_amount,
            cess_amount=line.cess_amount,
            line_total=money(
                line.taxable_amount + line.cgst_amount + line.sgst_amount
                + line.igst_amount + line.cess_amount
            ),
        )
        for line in order.items
    ]
    invoice = SalesInvoice(
        invoice_no=next_document_number(session, "INVOICE", invoice_date),
        customer_id=customer.id,
        order_id=order.id,
        status="ISSUED",
        currency=order.currency,
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=customer.credit_period_days),
        subtotal=order.subtotal,
        discount_total=order.discount_total,
        taxable_total=order.taxable_total,
        cgst_total=order.cgst_total,
        sgst_total=order.sgst_total,
        igst_total=order.igst_total,
        cess_total=order.cess_total,
        tax_total=order.tax_total,
        total=order.total,
        amount_paid=Decimal("0"),
        credit_total=Decimal("0"),
        balance_due=order.total,
        place_of_supply_state=customer.place_of_supply_state or customer.state,
        billing_address_snapshot=(
            order.billing_address_snapshot or customer.address
        ),
        shipping_address_snapshot=(
            order.shipping_address_snapshot or customer.address
        ),
        created_by_id=actor.id,
        issued_at=invoice_date,
        issued_by_id=actor.id,
        items=invoice_items,
    )
    session.add(invoice)
    session.flush()
    audit.record(
        session, actor_id=actor.id, action="CREATE", entity_type="INVOICE",
        entity_id=invoice.id,
        changes={
            "status": "ISSUED", "order_id": order.id, "total": invoice.total,
        },
    )
    return invoice


def create_invoice(
    session: Session,
    *,
    delivery_id: int,
    actor_id: int,
    quantities: dict[int, int],
    invoice_date: datetime | None = None,
) -> SalesInvoice:
    actor = _require_accounts(session, actor_id, "invoice.create")
    delivery = session.get(Delivery, delivery_id)
    if delivery is None or delivery.status != "CONFIRMED":
        raise InvoiceError("Invoices can only be created from confirmed deliveries.")
    if not quantities or any(qty <= 0 for qty in quantities.values()):
        raise InvoiceError("Enter at least one positive invoice quantity.")
    remaining = unbilled_quantities(session, delivery_id)
    items = {item.id: item for item in session.scalars(
        select(DeliveryItem).where(DeliveryItem.delivery_id == delivery_id)
    )}
    if any(item_id not in remaining or qty > remaining[item_id] for item_id, qty in quantities.items()):
        raise InvoiceError("Invoice quantity exceeds the uninvoiced delivered quantity.")

    order = session.get(Order, delivery.order_id)
    customer = session.get(Customer, order.customer_id)
    if order is None or customer is None:
        raise InvoiceError("Linked order or customer was not found.")
    if session.scalar(select(SalesInvoice.id).where(
        SalesInvoice.order_id == order.id, SalesInvoice.status != "CANCELLED",
    )):
        raise InvoiceError("This order already has an active invoice.")
    order_items = {
        line.id: line for line in session.scalars(
            select(OrderItem).where(OrderItem.id.in_([items[item_id].order_item_id for item_id in quantities]))
        )
    }
    invoice_date = invoice_date or datetime.now()
    invoice_lines = []
    for delivery_item_id, qty in quantities.items():
        order_item = order_items[items[delivery_item_id].order_item_id]
        destination = customer.place_of_supply_state or customer.state or config.COMPANY_STATE
        supply_type = "EXPORT" if customer.country_code.upper() != "IN" else "DOMESTIC"
        tax = calculate_gst(
            unit_price=order_item.unit_price,
            qty=qty,
            discount_pct=order_item.discount_pct,
            gst_rate=order_item.gst_rate,
            cess_rate=order_item.cess_rate,
            supplier_state=config.COMPANY_STATE,
            place_of_supply_state=destination,
            supply_type=supply_type,
        )
        invoice_lines.append((order_item, delivery_item_id, qty, tax))

    subtotal = sum((tax.gross for _, _, _, tax in invoice_lines), Decimal("0"))
    discount_total = sum((tax.discount for _, _, _, tax in invoice_lines), Decimal("0"))
    taxable_total = sum((tax.taxable for _, _, _, tax in invoice_lines), Decimal("0"))
    cgst_total = sum((tax.cgst for _, _, _, tax in invoice_lines), Decimal("0"))
    sgst_total = sum((tax.sgst for _, _, _, tax in invoice_lines), Decimal("0"))
    igst_total = sum((tax.igst for _, _, _, tax in invoice_lines), Decimal("0"))
    cess_total = sum((tax.cess for _, _, _, tax in invoice_lines), Decimal("0"))
    tax_total = cgst_total + sgst_total + igst_total + cess_total
    total = taxable_total + tax_total
    invoice = SalesInvoice(
        invoice_no=next_document_number(session, "INVOICE", invoice_date),
        customer_id=customer.id,
        order_id=order.id,
        status="DRAFT",
        currency="INR",
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=customer.credit_period_days),
        subtotal=money(subtotal),
        discount_total=money(discount_total),
        taxable_total=money(taxable_total),
        cgst_total=money(cgst_total),
        sgst_total=money(sgst_total),
        igst_total=money(igst_total),
        cess_total=money(cess_total),
        tax_total=money(tax_total),
        total=money(total),
        amount_paid=Decimal("0"),
        credit_total=Decimal("0"),
        balance_due=money(total),
        place_of_supply_state=customer.place_of_supply_state or customer.state,
        billing_address_snapshot=order.billing_address_snapshot or customer.address,
        shipping_address_snapshot=order.shipping_address_snapshot or customer.address,
        created_by_id=actor.id,
        items=[
            InvoiceItem(
                delivery_item_id=delivery_item_id,
                order_item_id=line.id,
                product_id=line.product_id,
                description=line.product.name,
                hsn_sac=line.hsn_sac,
                qty=qty,
                unit_price=line.unit_price,
                discount_pct=line.discount_pct,
                gst_rate=line.gst_rate,
                cess_rate=line.cess_rate,
                taxable_amount=tax.taxable,
                cgst_amount=tax.cgst,
                sgst_amount=tax.sgst,
                igst_amount=tax.igst,
                cess_amount=tax.cess,
                line_total=tax.total,
            )
            for line, delivery_item_id, qty, tax in invoice_lines
        ],
    )
    session.add(invoice)
    session.flush()
    audit.record(
        session, actor_id=actor.id, action="CREATE", entity_type="INVOICE",
        entity_id=invoice.id, changes={"status": "DRAFT", "total": invoice.total},
    )
    return invoice


def issue_invoice(session: Session, invoice_id: int, actor_id: int) -> SalesInvoice:
    actor = _require_accounts(session, actor_id, "invoice.issue")
    invoice = session.get(SalesInvoice, invoice_id)
    if invoice is None or invoice.status != "DRAFT":
        raise InvoiceError("Only draft invoices can be issued.")
    invoice.status = "ISSUED"
    invoice.issued_at = datetime.now()
    invoice.issued_by_id = actor.id
    audit.record(
        session, actor_id=actor.id, action="ISSUE", entity_type="INVOICE",
        entity_id=invoice.id, changes={"status": "ISSUED"},
    )
    return invoice


def cancel_invoice(session: Session, invoice_id: int, actor_id: int, reason: str) -> SalesInvoice:
    actor = _require_accounts(session, actor_id, "invoice.cancel")
    reason = reason.strip()
    invoice = session.get(SalesInvoice, invoice_id)
    if invoice is None or invoice.status not in {"DRAFT", "ISSUED"}:
        raise InvoiceError("This invoice cannot be cancelled; use a credit note for settled invoices.")
    if invoice.amount_paid or invoice.credit_total:
        raise InvoiceError("Invoices with payment or credit activity cannot be cancelled.")
    if not reason:
        raise InvoiceError("A cancellation reason is required.")
    invoice.status = "CANCELLED"
    invoice.cancelled_at = datetime.now()
    invoice.cancellation_reason = reason
    invoice.balance_due = Decimal("0")
    audit.record(
        session, actor_id=actor.id, action="CANCEL", entity_type="INVOICE",
        entity_id=invoice.id, changes={"reason": reason},
    )
    return invoice
