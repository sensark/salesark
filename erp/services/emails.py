from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from erp import config
from erp.db import session_scope
from erp.email_client import EmailClient, SendResult
from erp.models import (
    ROLE_ADMIN,
    ROLE_SALES_MANAGER,
    Customer,
    EmailLog,
    InvoiceItem,
    Order,
    OrderItem,
    Quotation,
    QuotationItem,
    SalesInvoice,
    User,
)

_env = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
    autoescape=select_autoescape(["html"]),
)

KIND_ORDER_CONFIRMATION = "order_confirmation"
KIND_ADMIN_NEW_ORDER = "admin_new_order"


def _client() -> EmailClient:
    return EmailClient()


def _load_order(session: Session, order_id: int) -> Order:
    return session.scalars(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.customer),
            selectinload(Order.sales_person),
        )
    ).one()


def _send_and_log(
    session: Session,
    client: EmailClient,
    to: list[str],
    subject: str,
    html: str,
    text: str,
    kind: str,
    order_id: int | None,
) -> SendResult:
    result = client.send(to, subject, html, text)
    status = "SKIPPED" if result.skipped else ("SENT" if result.ok else "FAILED")
    session.add(
        EmailLog(
            to_address=", ".join(to),
            subject=subject,
            html_body=html,
            text_body=text,
            kind=kind,
            status=status,
            error=result.error,
            order_id=order_id,
        )
    )
    return result


def _order_text(order: Order) -> str:
    lines = [
        f"Dear {order.customer.name},",
        "",
        f"Your order {order.order_no} has been approved.",
        "",
    ]
    for item in order.items:
        lines.append(
            f"- {item.product.name}: {item.qty} x {item.unit_price:.2f} "
            f"({item.discount_pct:.0f}% off) = {item.line_total:.2f}"
        )
    lines += [
        "",
        f"Subtotal: {order.subtotal:.2f}",
        f"Discount: -{order.discount_total:.2f}",
        f"Total: {order.total:.2f}",
        "",
        f"Questions? Contact {order.sales_person.name} at {order.sales_person.email}.",
        "",
        config.COMPANY_NAME,
    ]
    return "\n".join(lines)


def send_order_confirmation(order_id: int, client: EmailClient | None = None) -> SendResult:
    client = client or _client()
    with session_scope() as session:
        order = _load_order(session, order_id)
        html = _env.get_template("order_confirmation.html").render(order=order, company=config.COMPANY_NAME)
        subject = f"Order Confirmation {order.order_no} - {config.COMPANY_NAME}"
        return _send_and_log(
            session, client, [order.customer.email], subject, html, _order_text(order),
            KIND_ORDER_CONFIRMATION, order.id,
        )


def send_quotation(quotation_id: int, client: EmailClient | None = None) -> SendResult:
    client = client or _client()
    with session_scope() as session:
        quotation = session.get(Quotation, quotation_id)
        if quotation is None or quotation.status not in {"APPROVED", "SENT"}:
            return SendResult(ok=False, error="Only approved quotations can be emailed")
        customer = session.get(Customer, quotation.customer_id)
        items = list(session.scalars(
            select(QuotationItem).where(QuotationItem.quotation_id == quotation_id)
        ))
        html = _env.get_template("quotation.html").render(
            quotation=quotation, customer=customer, items=items, company=config.COMPANY_NAME
        )
        lines = [
            f"Quotation {quotation.quotation_no} for {customer.name}",
            f"Valid until: {quotation.valid_until:%d %b %Y}" if quotation.valid_until else "",
            "",
            *[f"{item.description}: {item.qty} x {item.unit_price:.2f} = {item.line_total:.2f}"
              for item in items],
            "",
            f"Total: INR {quotation.total:.2f}",
            quotation.terms or "",
        ]
        return _send_and_log(
            session, client, [customer.email],
            f"Quotation {quotation.quotation_no} - {config.COMPANY_NAME}",
            html, "\n".join(line for line in lines if line), "quotation", None,
        )


def render_invoice(invoice_id: int) -> tuple[str, str, str]:
    with session_scope() as session:
        invoice = session.get(SalesInvoice, invoice_id)
        if invoice is None:
            raise ValueError("Invoice not found")
        if invoice.status not in {"ISSUED", "PARTIALLY_PAID", "PAID"}:
            raise ValueError("Only issued invoices can be rendered")
        customer = session.get(Customer, invoice.customer_id)
        items = list(session.scalars(
            select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
        ))
        html = _env.get_template("sales_invoice.html").render(
            invoice=invoice, customer=customer, items=items, company=config.COMPANY_NAME,
        )
        subject = f"Tax Invoice {invoice.invoice_no} - {config.COMPANY_NAME}"
        text = "\n".join([
            f"Tax Invoice {invoice.invoice_no}",
            f"Customer: {customer.name}",
            f"Invoice date: {invoice.invoice_date:%d %b %Y}",
            f"Taxable value: INR {invoice.taxable_total:.2f}",
            f"CGST: INR {invoice.cgst_total:.2f}",
            f"SGST: INR {invoice.sgst_total:.2f}",
            f"IGST: INR {invoice.igst_total:.2f}",
            f"Cess: INR {invoice.cess_total:.2f}",
            f"Total: INR {invoice.total:.2f}",
            f"Balance due: INR {invoice.balance_due:.2f}",
        ])
        return html, subject, text


def send_invoice(invoice_id: int, client: EmailClient | None = None) -> SendResult:
    client = client or _client()
    try:
        html, subject, text = render_invoice(invoice_id)
    except ValueError as exc:
        return SendResult(ok=False, error=str(exc))
    with session_scope() as session:
        invoice = session.get(SalesInvoice, invoice_id)
        customer = session.get(Customer, invoice.customer_id)
        return _send_and_log(
            session, client, [customer.email], subject, html, text,
            "sales_invoice", invoice.order_id,
        )


def send_admin_new_order_alert(order_id: int, client: EmailClient | None = None) -> SendResult:
    client = client or _client()
    with session_scope() as session:
        order = _load_order(session, order_id)
        recipient_roles = (
            [ROLE_ADMIN]
            if order.required_approver_role == ROLE_ADMIN
            else [ROLE_ADMIN, ROLE_SALES_MANAGER]
        )
        recipients = config.ADMIN_NOTIFY_EMAIL or list(
            session.scalars(select(User.email).where(User.role.in_(recipient_roles), User.active.is_(True)))
        )
        low_stock = [i.product.name for i in order.items if i.product.stock - i.qty <= i.product.reorder_level]
        html = _env.get_template("admin_new_order.html").render(order=order, low_stock=low_stock)
        text = (
            f"New order {order.order_no} requires approval.\n"
            f"Customer: {order.customer.name}\nSales person: {order.sales_person.name}\n"
            f"Total: {order.total:.2f}\n"
            + (f"Low stock on: {', '.join(low_stock)}\n" if low_stock else "")
        )
        return _send_and_log(
            session, client, recipients, f"Approval required: order {order.order_no}", html, text,
            KIND_ADMIN_NEW_ORDER, order.id,
        )


def resend(log_id: int, client: EmailClient | None = None) -> SendResult:
    client = client or _client()
    with session_scope() as session:
        entry = session.get(EmailLog, log_id)
        if entry is None:
            return SendResult(ok=False, error="Email log entry not found")
        to = [a.strip() for a in entry.to_address.split(",") if a.strip()]
        return _send_and_log(
            session, client, to, entry.subject, entry.html_body, entry.text_body, entry.kind, entry.order_id
        )
