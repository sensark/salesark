from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    event,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from erp.config import DEFAULT_REORDER_LEVEL

ROLE_ADMIN = "admin"
ROLE_SALES = "sales_person"
ROLE_ADMIN_OWNER = ROLE_ADMIN
ROLE_SALES_EXECUTIVE = ROLE_SALES
ROLE_SALES_MANAGER = "sales_manager"
ROLE_ACCOUNTS = "accounts"
ROLE_WAREHOUSE = "warehouse"
ROLES = (
    ROLE_ADMIN_OWNER,
    ROLE_SALES_EXECUTIVE,
    ROLE_SALES_MANAGER,
    ROLE_ACCOUNTS,
    ROLE_WAREHOUSE,
)

STATUS_PENDING = "PENDING"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_CANCELLED = "CANCELLED"
ORDER_STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_CANCELLED)

REGIONS = ("North", "South", "East", "West", "Central")
INDIAN_STATES = (
    "Andhra Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Odisha", "Punjab", "Rajasthan", "Tamil Nadu", "Telangana",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
)

Money = Numeric(12, 2)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_target: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    company: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    region: Mapped[str] = mapped_column(String(30))
    city: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(Text)
    customer_type: Mapped[str] = mapped_column(String(30), default="BUSINESS")
    customer_status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    contact_person: Mapped[str | None] = mapped_column(String(120))
    gstin: Mapped[str | None] = mapped_column(String(15), index=True)
    pan: Mapped[str | None] = mapped_column(String(10))
    gst_registration_type: Mapped[str] = mapped_column(String(30), default="UNREGISTERED")
    state: Mapped[str | None] = mapped_column(String(80))
    country_code: Mapped[str] = mapped_column(String(2), default="IN")
    place_of_supply_state: Mapped[str | None] = mapped_column(String(80))
    credit_limit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    credit_period_days: Mapped[int] = mapped_column(Integer, default=0)
    price_list_id: Mapped[int | None] = mapped_column(ForeignKey("price_lists.id"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    created_by: Mapped[User | None] = relationship()
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    addresses: Mapped[list["CustomerAddress"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(60), index=True)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    cost_price: Mapped[Decimal | None] = mapped_column(Money)
    unit: Mapped[str] = mapped_column(String(20), default="EA")
    hsn_sac: Mapped[str | None] = mapped_column(String(20))
    tax_category: Mapped[str] = mapped_column(String(40), default="STANDARD")
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    reorder_level: Mapped[int] = mapped_column(Integer, default=DEFAULT_REORDER_LEVEL)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    tiers: Mapped[list["DiscountTier"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="DiscountTier.min_qty",
    )

    @property
    def is_low_stock(self) -> bool:
        return self.stock <= self.reorder_level


class DiscountTier(Base):
    __tablename__ = "discount_tiers"
    __table_args__ = (UniqueConstraint("product_id", "min_qty"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    min_qty: Mapped[int] = mapped_column(Integer)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    product: Mapped[Product] = relationship(back_populates="tiers")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    sales_person_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, index=True)
    fulfillment_status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    credit_limit_exceeded: Mapped[bool] = mapped_column(Boolean, default=False)
    required_approver_role: Mapped[str] = mapped_column(String(30), default=ROLE_SALES_MANAGER)
    cancelled_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    subtotal: Mapped[Decimal] = mapped_column(Money)
    discount_total: Mapped[Decimal] = mapped_column(Money)
    total: Mapped[Decimal] = mapped_column(Money)
    taxable_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cgst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cess_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    advance_payment_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0")
    )
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    customer_po_number: Mapped[str | None] = mapped_column(String(80))
    expected_delivery_date: Mapped[datetime | None] = mapped_column(DateTime)
    billing_address_snapshot: Mapped[str | None] = mapped_column(Text)
    shipping_address_snapshot: Mapped[str | None] = mapped_column(Text)
    source_quotation_id: Mapped[int | None] = mapped_column(ForeignKey("quotations.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer] = relationship(back_populates="orders")
    sales_person: Mapped[User] = relationship(foreign_keys=[sales_person_id])
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id])
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    hsn_sac: Mapped[str | None] = mapped_column(String(20))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    taxable_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cgst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cess_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Money)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class EmailLog(Base):
    __tablename__ = "email_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    to_address: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(300))
    html_body: Mapped[str] = mapped_column(Text)
    text_body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(40), default="Other")
    address_type: Mapped[str] = mapped_column(String(20))
    contact_person: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    line1: Mapped[str] = mapped_column(String(200))
    line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(80))
    district: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(80))
    postal_code: Mapped[str] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(2), default="IN")
    is_default_billing: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default_shipping: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    customer: Mapped[Customer] = relationship(back_populates="addresses")


class TaxRate(Base):
    __tablename__ = "tax_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)


class PriceList(Base):
    __tablename__ = "price_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)


class PriceListItem(Base):
    __tablename__ = "price_list_items"
    __table_args__ = (UniqueConstraint("price_list_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    unit_price: Mapped[Decimal] = mapped_column(Money)


class CustomerProductPrice(Base):
    __tablename__ = "customer_product_prices"
    __table_args__ = (UniqueConstraint("customer_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)


class QuantityPriceTier(Base):
    __tablename__ = "quantity_price_tiers"
    __table_args__ = (UniqueConstraint("product_id", "min_qty"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    min_qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)


class DocumentSeries(Base):
    __tablename__ = "document_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_type: Mapped[str] = mapped_column(String(30), unique=True)
    prefix: Mapped[str] = mapped_column(String(12))
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=4)
    next_number: Mapped[int] = mapped_column(Integer, default=1)
    padding: Mapped[int] = mapped_column(Integer, default=6)


class Quotation(Base):
    __tablename__ = "quotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    sales_person_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    subtotal: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    taxable_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cgst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cess_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    billing_address_snapshot: Mapped[str | None] = mapped_column(Text)
    shipping_address_snapshot: Mapped[str | None] = mapped_column(Text)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    converted_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    items: Mapped[list["QuotationItem"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )


class QuotationItem(Base):
    __tablename__ = "quotation_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    description: Mapped[str] = mapped_column(String(200))
    hsn_sac: Mapped[str | None] = mapped_column(String(20))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    taxable_amount: Mapped[Decimal] = mapped_column(Money)
    cgst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cess_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Money)

    quotation: Mapped[Quotation] = relationship(back_populates="items")


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WarehouseStock(Base):
    __tablename__ = "warehouse_stock"
    __table_args__ = (UniqueConstraint("warehouse_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    dispatch_date: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    transport_name: Mapped[str | None] = mapped_column(String(120))
    tracking_number: Mapped[str | None] = mapped_column(String(100))
    receiver_name: Mapped[str | None] = mapped_column(String(120))
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    items: Mapped[list["DeliveryItem"]] = relationship(
        back_populates="delivery", cascade="all, delete-orphan"
    )


class DeliveryItem(Base):
    __tablename__ = "delivery_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"), index=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer)

    delivery: Mapped[Delivery] = relationship(back_populates="items")


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        UniqueConstraint("source_type", "source_line_id"),
        Index("ix_inventory_product_time", "product_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[int] = mapped_column(Integer)
    source_line_id: Mapped[int | None] = mapped_column(Integer)
    qty_delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class SalesInvoice(Base):
    __tablename__ = "sales_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    invoice_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    due_date: Mapped[datetime | None] = mapped_column(DateTime)
    subtotal: Mapped[Decimal] = mapped_column(Money)
    discount_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    taxable_total: Mapped[Decimal] = mapped_column(Money)
    cgst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cess_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Money)
    charges_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    round_off: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money)
    amount_paid: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    credit_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    debit_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    balance_due: Mapped[Decimal] = mapped_column(Money)
    place_of_supply_state: Mapped[str | None] = mapped_column(String(80))
    billing_address_snapshot: Mapped[str | None] = mapped_column(Text)
    shipping_address_snapshot: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime)
    issued_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoices.id", ondelete="CASCADE"), index=True)
    delivery_item_id: Mapped[int | None] = mapped_column(ForeignKey("delivery_items.id"), index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    description: Mapped[str] = mapped_column(String(200))
    hsn_sac: Mapped[str | None] = mapped_column(String(20))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    taxable_amount: Mapped[Decimal] = mapped_column(Money)
    cgst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cess_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Money)

    invoice: Mapped[SalesInvoice] = relationship(back_populates="items")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    payment_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    amount: Mapped[Decimal] = mapped_column(Money)
    method: Mapped[str] = mapped_column(String(30))
    reference: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="UNRECONCILED", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (UniqueConstraint("payment_id", "invoice_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoices.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    allocated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class SalesReturn(Base):
    __tablename__ = "sales_returns"

    id: Mapped[int] = mapped_column(primary_key=True)
    return_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoices.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED", index=True)
    reason: Mapped[str] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    items: Mapped[list["SalesReturnItem"]] = relationship(
        back_populates="sales_return", cascade="all, delete-orphan"
    )


class SalesReturnItem(Base):
    __tablename__ = "sales_return_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("sales_returns.id", ondelete="CASCADE"), index=True)
    invoice_item_id: Mapped[int] = mapped_column(ForeignKey("invoice_items.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    restock: Mapped[bool] = mapped_column(Boolean, default=True)

    sales_return: Mapped[SalesReturn] = relationship(back_populates="items")


class CreditNote(Base):
    __tablename__ = "credit_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    note_type: Mapped[str] = mapped_column(String(10), default="CREDIT")
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoices.id"), index=True)
    return_id: Mapped[int | None] = mapped_column(ForeignKey("sales_returns.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    reason: Mapped[str] = mapped_column(String(40))
    subtotal: Mapped[Decimal] = mapped_column(Money)
    taxable_total: Mapped[Decimal] = mapped_column(Money)
    cgst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cess_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime)
    issued_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    items: Mapped[list["CreditNoteItem"]] = relationship(
        back_populates="credit_note", cascade="all, delete-orphan"
    )


class CreditNoteItem(Base):
    __tablename__ = "credit_note_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_note_id: Mapped[int] = mapped_column(ForeignKey("credit_notes.id", ondelete="CASCADE"), index=True)
    invoice_item_id: Mapped[int] = mapped_column(ForeignKey("invoice_items.id"))
    qty: Mapped[int] = mapped_column(Integer)
    taxable_amount: Mapped[Decimal] = mapped_column(Money)
    cgst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    sgst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    igst_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cess_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Money)

    credit_note: Mapped[CreditNote] = relationship(back_populates="items")


class ApprovalRule(Base):
    __tablename__ = "approval_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    rule_type: Mapped[str] = mapped_column(String(30))
    threshold: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    approver_role: Mapped[str] = mapped_column(String(30), default=ROLE_SALES_MANAGER)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SalesAuditLog(Base):
    __tablename__ = "sales_audit_logs"
    __table_args__ = (Index("ix_sales_audit_entity", "entity_type", "entity_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(Integer)
    changes_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


@event.listens_for(SalesAuditLog, "before_update")
def _prevent_audit_update(_mapper, _connection, _target):
    raise ValueError("Sales audit logs are append-only.")


@event.listens_for(SalesAuditLog, "before_delete")
def _prevent_audit_delete(_mapper, _connection, _target):
    raise ValueError("Sales audit logs are append-only.")


class AccountingExport(Base):
    __tablename__ = "accounting_exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    export_no: Mapped[str] = mapped_column(String(40), unique=True)
    date_from: Mapped[datetime] = mapped_column(DateTime)
    date_to: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="GENERATED")
    file_name: Mapped[str] = mapped_column(String(200))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    exported_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    exported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    external_reference: Mapped[str | None] = mapped_column(String(120))


class AccountingMapping(Base):
    __tablename__ = "accounting_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(40), unique=True)
    account_code: Mapped[str] = mapped_column(String(40))
    account_name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MLModelRun(Base):
    __tablename__ = "ml_model_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(40), index=True)
    method: Mapped[str] = mapped_column(String(60))
    n_samples: Mapped[int] = mapped_column(Integer, default=0)
    metrics_json: Mapped[str | None] = mapped_column(Text)
    artifact_path: Mapped[str | None] = mapped_column(String(300))
    trained_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    trained_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class CustomerScore(Base):
    __tablename__ = "customer_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), unique=True)
    sales_person_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    churn_probability: Mapped[float] = mapped_column(Float, default=0.0)
    churn_drivers: Mapped[str | None] = mapped_column(Text)
    clv_90d: Mapped[float] = mapped_column(Float, default=0.0)
    value_at_risk: Mapped[float] = mapped_column(Float, default=0.0)
    segment: Mapped[str | None] = mapped_column(String(30))
    recency_days: Mapped[int] = mapped_column(Integer, default=0)
    frequency: Mapped[int] = mapped_column(Integer, default=0)
    monetary: Mapped[float] = mapped_column(Float, default=0.0)
    recommended_action: Mapped[str | None] = mapped_column(String(200))
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class InvoiceRiskScore(Base):
    __tablename__ = "invoice_risk_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoices.id", ondelete="CASCADE"), unique=True)
    late_probability: Mapped[float] = mapped_column(Float, default=0.0)
    risk_band: Mapped[str] = mapped_column(String(10), default="LOW")
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class QuotationScore(Base):
    __tablename__ = "quotation_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id", ondelete="CASCADE"), unique=True)
    win_probability: Mapped[float] = mapped_column(Float, default=0.0)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ProductForecast(Base):
    __tablename__ = "product_forecasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), unique=True)
    method: Mapped[str] = mapped_column(String(40))
    weekly_demand: Mapped[float] = mapped_column(Float, default=0.0)
    demand_std: Mapped[float] = mapped_column(Float, default=0.0)
    forecast_30d: Mapped[float] = mapped_column(Float, default=0.0)
    forecast_json: Mapped[str | None] = mapped_column(Text)
    reorder_point: Mapped[int] = mapped_column(Integer, default=0)
    suggested_qty: Mapped[int] = mapped_column(Integer, default=0)
    days_of_cover: Mapped[float | None] = mapped_column(Float)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


ML_TABLES = (MLModelRun, CustomerScore, InvoiceRiskScore, QuotationScore, ProductForecast)
