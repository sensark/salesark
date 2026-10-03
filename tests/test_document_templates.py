from datetime import datetime
from decimal import Decimal
from pathlib import Path
import re

from jinja2 import Environment, FileSystemLoader, select_autoescape

from erp.models import (
    InvoiceItem,
    SalesInvoice,
)
from erp.services.orders import CartLine, place_order, get_order
from erp.services.quotations import create_quotation


TEMPLATES = Path(__file__).resolve().parents[1] / "erp" / "templates"
ENV = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


def test_transaction_documents_render_with_shared_visual_system(session, data):
    order = place_order(
        session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
        lines=[CartLine(data["pen"].id, 12)],
    )
    hydrated_order = get_order(session, order.id)
    quote = create_quotation(
        session, customer_id=data["customer"].id, sales_person_id=data["sales"].id,
        lines=[CartLine(data["pen"].id, 12)],
    )
    invoice = SalesInvoice(
        invoice_no="INV-DEMO-001", customer_id=data["customer"].id, order_id=order.id,
        status="ISSUED", currency="INR", invoice_date=datetime.now(),
        subtotal=Decimal("120"), discount_total=Decimal("6"), taxable_total=Decimal("114"),
        cgst_total=Decimal("10.26"), sgst_total=Decimal("10.26"), igst_total=Decimal("0"),
        cess_total=Decimal("0"), tax_total=Decimal("20.52"), charges_total=Decimal("0"),
        round_off=Decimal("0"), total=Decimal("134.52"), amount_paid=Decimal("0"),
        credit_total=Decimal("0"), debit_total=Decimal("0"), balance_due=Decimal("134.52"),
        created_by_id=data["admin"].id,
    )
    invoice_item = InvoiceItem(
        invoice_id=1, delivery_item_id=1, product_id=data["pen"].id,
        description=data["pen"].name, hsn_sac="DEMO-HSN", qty=12,
        unit_price=Decimal("10"), discount_pct=Decimal("5"), gst_rate=Decimal("18"),
        cess_rate=Decimal("0"), taxable_amount=Decimal("114"),
        cgst_amount=Decimal("10.26"), sgst_amount=Decimal("10.26"),
        igst_amount=Decimal("0"), cess_amount=Decimal("0"), line_total=Decimal("134.52"),
    )
    session.add(invoice)
    session.flush()

    contexts = {
        "order_confirmation.html": {"order": hydrated_order, "company": "Krypton Industries Limited"},
        "admin_new_order.html": {"order": hydrated_order, "low_stock": [], "company": "Krypton Industries Limited"},
        "quotation.html": {
            "quotation": quote, "customer": data["customer"], "items": quote.items,
            "company": "Krypton Industries Limited",
        },
        "sales_invoice.html": {
            "invoice": invoice, "customer": data["customer"], "items": [invoice_item],
            "company": "Krypton Industries Limited",
        },
    }
    for name, context in contexts.items():
        html = ENV.get_template(name).render(**context)
        assert re.search(r"max-width:\s*640px", html)
        assert "#0b1f3a" in html and "#ff7a00" in html
        assert "INR" in html
        assert "Krypton Industries Limited" in html
