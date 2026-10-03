import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.models import (
    Customer,
    Delivery,
    DeliveryItem,
    InvoiceItem,
    Order,
    OrderItem,
    Payment,
    PaymentAllocation,
    Product,
    SalesInvoice,
    SalesReturn,
    SalesReturnItem,
    User,
    Warehouse,
)


def sales_lines(session: Session) -> pd.DataFrame:
    stmt = (
        select(
            Order.order_no, Order.created_at, Order.status, Order.fulfillment_status,
            Order.total.label("order_total"),
            Customer.name.label("customer"), Customer.region, Customer.state,
            User.name.label("sales_person"),
            Product.sku, Product.name.label("product"), Product.category, Product.hsn_sac,
            OrderItem.qty, OrderItem.unit_price, OrderItem.discount_pct,
            OrderItem.taxable_amount, OrderItem.cgst_amount, OrderItem.sgst_amount,
            OrderItem.igst_amount, OrderItem.cess_amount, OrderItem.line_total,
        )
        .join(Customer, Customer.id == Order.customer_id)
        .join(User, User.id == Order.sales_person_id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Order.status == "APPROVED")
    )
    df = pd.DataFrame(session.execute(stmt).mappings().all())
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"])
        for column in ("unit_price", "taxable_amount", "cgst_amount", "sgst_amount", "igst_amount", "cess_amount", "line_total", "order_total"):
            df[column] = df[column].astype(float)
        df["tax_total"] = df["cgst_amount"] + df["sgst_amount"] + df["igst_amount"] + df["cess_amount"]
    return df


def invoice_lines(session: Session) -> pd.DataFrame:
    stmt = (
        select(
            SalesInvoice.invoice_no, SalesInvoice.invoice_date, SalesInvoice.due_date,
            SalesInvoice.status, SalesInvoice.total.label("invoice_total"),
            SalesInvoice.amount_paid, SalesInvoice.credit_total, SalesInvoice.debit_total,
            SalesInvoice.balance_due, SalesInvoice.place_of_supply_state,
            Customer.name.label("customer"), Customer.region,
            InvoiceItem.description.label("product"), InvoiceItem.hsn_sac,
            InvoiceItem.qty, InvoiceItem.gst_rate, InvoiceItem.taxable_amount,
            InvoiceItem.cgst_amount, InvoiceItem.sgst_amount, InvoiceItem.igst_amount,
            InvoiceItem.cess_amount, InvoiceItem.line_total,
        )
        .join(Customer, Customer.id == SalesInvoice.customer_id)
        .join(InvoiceItem, InvoiceItem.invoice_id == SalesInvoice.id)
        .where(SalesInvoice.status != "CANCELLED")
    )
    df = pd.DataFrame(session.execute(stmt).mappings().all())
    if not df.empty:
        df["invoice_date"] = pd.to_datetime(df["invoice_date"])
        for column in ("invoice_total", "amount_paid", "credit_total", "debit_total", "balance_due",
                       "taxable_amount", "cgst_amount", "sgst_amount", "igst_amount", "cess_amount", "line_total"):
            df[column] = df[column].astype(float)
    return df


def delivery_lines(session: Session) -> pd.DataFrame:
    stmt = (
        select(
            Delivery.delivery_no, Delivery.status.label("delivery_status"), Delivery.confirmed_at,
            Order.order_no, Order.fulfillment_status, Customer.name.label("customer"), Customer.region,
            Warehouse.code.label("warehouse"), Product.sku, Product.name.label("product"),
            DeliveryItem.qty, User.name.label("sales_person"),
        )
        .join(Order, Order.id == Delivery.order_id)
        .join(Customer, Customer.id == Order.customer_id)
        .join(Warehouse, Warehouse.id == Delivery.warehouse_id)
        .join(DeliveryItem, DeliveryItem.delivery_id == Delivery.id)
        .join(OrderItem, OrderItem.id == DeliveryItem.order_item_id)
        .join(Product, Product.id == OrderItem.product_id)
        .join(User, User.id == Order.sales_person_id)
    )
    df = pd.DataFrame(session.execute(stmt).mappings().all())
    if not df.empty:
        df["confirmed_at"] = pd.to_datetime(df["confirmed_at"])
    return df


def return_lines(session: Session) -> pd.DataFrame:
    stmt = (
        select(
            SalesReturn.return_no, SalesReturn.created_at, SalesReturn.status, SalesReturn.reason,
            Customer.name.label("customer"), Customer.region, SalesInvoice.invoice_no,
            InvoiceItem.description.label("product"), InvoiceItem.hsn_sac,
            SalesReturnItem.qty, SalesReturnItem.restock,
        )
        .join(Customer, Customer.id == SalesReturn.customer_id)
        .join(SalesInvoice, SalesInvoice.id == SalesReturn.invoice_id)
        .join(SalesReturnItem, SalesReturnItem.return_id == SalesReturn.id)
        .join(InvoiceItem, InvoiceItem.id == SalesReturnItem.invoice_item_id)
    )
    df = pd.DataFrame(session.execute(stmt).mappings().all())
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"])
    return df


def collection_lines(session: Session) -> pd.DataFrame:
    stmt = (
        select(
            Payment.receipt_no, Payment.payment_date, Payment.method, Payment.status.label("receipt_status"),
            PaymentAllocation.amount.label("allocated_amount"), SalesInvoice.invoice_no,
            Customer.name.label("customer"), Customer.region, User.name.label("sales_person"),
        )
        .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
        .join(SalesInvoice, SalesInvoice.id == PaymentAllocation.invoice_id)
        .join(Customer, Customer.id == Payment.customer_id)
        .join(Order, Order.id == SalesInvoice.order_id)
        .join(User, User.id == Order.sales_person_id)
    )
    df = pd.DataFrame(session.execute(stmt).mappings().all())
    if not df.empty:
        df["payment_date"] = pd.to_datetime(df["payment_date"])
        df["allocated_amount"] = df["allocated_amount"].astype(float)
    return df


def filter_dates(df: pd.DataFrame, column: str, start, end, regions: list[str] | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    date_values = pd.to_datetime(df[column]).dt.date
    mask = (date_values >= start) & (date_values <= end)
    if regions and "region" in df:
        mask &= df["region"].isin(regions)
    return df[mask]
