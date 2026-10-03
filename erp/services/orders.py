from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from erp.models import (
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_PENDING,
    STATUS_REJECTED,
    ROLE_ADMIN,
    ROLE_SALES,
    ROLE_SALES_MANAGER,
    Customer,
    Delivery,
    Order,
    OrderItem,
    Product,
    ApprovalRule,
    User,
)
from erp import config
from erp.permissions import require_action
from erp.services import notifications
from erp.services import audit, inventory
from erp.services.credit import review_required
from erp.services.documents import next_document_number
from erp.services.discounts import discount_for, money
from erp.services.pricing import resolve_unit_price
from erp.services.tax import TaxBreakdown, calculate_gst


class OrderError(ValueError):
    pass


class InsufficientStockError(OrderError):
    def __init__(self, shortages: list[tuple[str, int, int]]):
        self.shortages = shortages
        detail = "; ".join(f"{name} (requested {req}, available {avail})" for name, req, avail in shortages)
        super().__init__(f"Insufficient stock: {detail}")


@dataclass(frozen=True)
class CartLine:
    product_id: int
    qty: int


@dataclass
class PricedLine:
    product: Product
    qty: int
    unit_price: Decimal
    discount_pct: Decimal
    gross: Decimal
    line_total: Decimal
    tax: TaxBreakdown

    @property
    def discount_amount(self) -> Decimal:
        return self.gross - self.line_total


def _merge(lines: list[CartLine]) -> dict[int, int]:
    merged: dict[int, int] = defaultdict(int)
    for line in lines:
        if line.qty <= 0:
            raise OrderError("Quantities must be greater than zero.")
        merged[line.product_id] += line.qty
    return merged


def approval_requirement(
    session: Session,
    *,
    customer: Customer,
    total: Decimal,
    discount_pct: Decimal,
) -> tuple[bool, str]:
    credit_exceeded = review_required(
        session,
        customer_id=customer.id,
        credit_limit=customer.credit_limit,
        order_total=money(total),
    )
    admin_required = False
    for rule in session.scalars(select(ApprovalRule).where(ApprovalRule.active.is_(True))):
        matches_value = rule.rule_type == "ORDER_VALUE" and total >= rule.threshold
        matches_discount = rule.rule_type == "DISCOUNT_PCT" and discount_pct >= rule.threshold
        if (matches_value or matches_discount) and rule.approver_role == ROLE_ADMIN:
            admin_required = True
    return credit_exceeded, ROLE_ADMIN if admin_required else ROLE_SALES_MANAGER


def price_cart(
    session: Session,
    lines: list[CartLine],
    customer_id: int | None = None,
) -> list[PricedLine]:
    """Price lines from the database so client-side values are never trusted."""
    merged = _merge(lines)
    if not merged:
        raise OrderError("The order has no items.")
    products = {
        p.id: p
        for p in session.scalars(
            select(Product).where(Product.id.in_(merged)).options(selectinload(Product.tiers))
        )
    }
    customer = session.get(Customer, customer_id) if customer_id else None
    destination_state = (
        (customer.place_of_supply_state or customer.state)
        if customer
        else config.COMPANY_STATE
    ) or config.COMPANY_STATE
    supply_type = "EXPORT" if customer and customer.country_code.upper() != "IN" else "DOMESTIC"
    priced = []
    for product_id, qty in merged.items():
        product = products.get(product_id)
        if product is None or not product.active:
            raise OrderError("One of the selected products is no longer available.")
        resolved = resolve_unit_price(
            session,
            product,
            qty,
            customer_id=customer_id,
            price_list_id=customer.price_list_id if customer else None,
        )
        pct = discount_for(product.tiers, qty)
        tax = calculate_gst(
            unit_price=resolved.unit_price,
            qty=qty,
            discount_pct=pct,
            gst_rate=product.gst_rate,
            cess_rate=product.cess_rate,
            supplier_state=config.COMPANY_STATE,
            place_of_supply_state=destination_state,
            supply_type=supply_type,
        )
        priced.append(
            PricedLine(
                product=product,
                qty=qty,
                unit_price=money(resolved.unit_price),
                discount_pct=pct,
                gross=tax.gross,
                line_total=tax.taxable,
                tax=tax,
            )
        )
    return priced


def place_order(
    session: Session,
    *,
    sales_person_id: int,
    customer_id: int,
    lines: list[CartLine],
    notes: str = "",
    advance_payment_pct: Decimal | int | float = Decimal("0"),
    created_at: datetime | None = None,
) -> Order:
    salesperson = session.get(User, sales_person_id)
    if salesperson is None:
        raise OrderError("Sales person not found.")
    try:
        require_action(salesperson.role, "order.create")
    except PermissionError as exc:
        raise OrderError(str(exc)) from exc
    customer = session.get(Customer, customer_id)
    if customer is None or customer.customer_status != "ACTIVE":
        raise OrderError("Customer not found.")
    advance_payment_pct = Decimal(str(advance_payment_pct)).quantize(
        Decimal("0.01")
    )
    if not Decimal("0") <= advance_payment_pct <= Decimal("100"):
        raise OrderError(
            "Advance payment percentage must be between 0 and 100."
        )
    priced = price_cart(session, lines, customer_id=customer.id)
    created_at = created_at or datetime.now()
    subtotal = sum((p.gross for p in priced), Decimal("0"))
    total = sum((p.tax.total for p in priced), Decimal("0"))
    taxable_total = sum((p.tax.taxable for p in priced), Decimal("0"))
    cgst_total = sum((p.tax.cgst for p in priced), Decimal("0"))
    sgst_total = sum((p.tax.sgst for p in priced), Decimal("0"))
    igst_total = sum((p.tax.igst for p in priced), Decimal("0"))
    cess_total = sum((p.tax.cess for p in priced), Decimal("0"))
    discount_pct = (subtotal - taxable_total) * Decimal("100") / subtotal if subtotal else Decimal("0")
    credit_exceeded, required_role = approval_requirement(
        session, customer=customer, total=money(total), discount_pct=discount_pct,
    )

    order = Order(
        order_no=next_document_number(session, "ORDER", created_at),
        customer_id=customer.id,
        sales_person_id=sales_person_id,
        status=STATUS_PENDING,
        subtotal=money(subtotal),
        discount_total=money(subtotal - taxable_total),
        total=money(total),
        taxable_total=money(taxable_total),
        cgst_total=money(cgst_total),
        sgst_total=money(sgst_total),
        igst_total=money(igst_total),
        cess_total=money(cess_total),
        tax_total=money(cgst_total + sgst_total + igst_total + cess_total),
        advance_payment_pct=advance_payment_pct,
        currency="INR",
        credit_limit_exceeded=credit_exceeded,
        required_approver_role=required_role,
        notes=notes.strip() or None,
        created_at=created_at,
        items=[
            OrderItem(
                product_id=p.product.id, qty=p.qty, unit_price=p.unit_price,
                discount_pct=p.discount_pct, hsn_sac=p.product.hsn_sac,
                gst_rate=p.tax.cgst_rate + p.tax.sgst_rate + p.tax.igst_rate,
                cess_rate=p.tax.cess_rate, taxable_amount=p.tax.taxable,
                cgst_amount=p.tax.cgst, sgst_amount=p.tax.sgst,
                igst_amount=p.tax.igst, cess_amount=p.tax.cess,
                line_total=p.line_total,
            )
            for p in priced
        ],
    )
    session.add(order)
    session.flush()
    audit.record(
        session, actor_id=sales_person_id, action="CREATE", entity_type="ORDER",
        entity_id=order.id, changes={"status": STATUS_PENDING, "total": order.total},
    )
    notifications.notify_approvers(
        session,
        required_role,
        f"New order {order.order_no} from {customer.name} ({order.total:,.2f}) awaits approval.",
        order.id,
    )
    return order


def get_order(session: Session, order_id: int) -> Order | None:
    return session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.customer),
            selectinload(Order.sales_person),
        )
    )


def list_orders(
    session: Session,
    *,
    status: str | None = None,
    sales_person_id: int | None = None,
    required_approver_role: str | None = None,
    limit: int = 200,
) -> list[Order]:
    stmt = (
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.customer),
            selectinload(Order.sales_person),
        )
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Order.status == status)
    if sales_person_id:
        stmt = stmt.where(Order.sales_person_id == sales_person_id)
    if required_approver_role:
        stmt = stmt.where(Order.required_approver_role == required_approver_role)
    return list(session.scalars(stmt))


def filter_approval_queue(
    orders: list[Order],
    *,
    search: str = "",
    customer_ids: set[int] | None = None,
    salesperson_ids: set[int] | None = None,
    regions: set[str] | None = None,
    start_date=None,
    end_date=None,
    risk: str = "All",
    shortages_by_order: dict[int, list[tuple[str, int, int]]] | None = None,
) -> list[Order]:
    search = search.strip().casefold()
    customer_ids = customer_ids or set()
    salesperson_ids = salesperson_ids or set()
    regions = regions or set()
    shortages_by_order = shortages_by_order or {}
    filtered = []
    for order in orders:
        if customer_ids and order.customer_id not in customer_ids:
            continue
        if salesperson_ids and order.sales_person_id not in salesperson_ids:
            continue
        if regions and order.customer.region not in regions:
            continue
        order_date = order.created_at.date()
        if start_date and order_date < start_date:
            continue
        if end_date and order_date > end_date:
            continue
        item_matches = any(
            search in item.product.name.casefold() or search in item.product.sku.casefold()
            for item in order.items
        ) if search else False
        searchable = " ".join((
            order.order_no,
            order.customer.name,
            order.customer.company or "",
            order.sales_person.name,
        )).casefold()
        if search and search not in searchable and not item_matches:
            continue
        shortages = shortages_by_order.get(order.id, [])
        low_stock = any(
            item.product.stock >= item.qty
            and item.product.stock - item.qty <= item.product.reorder_level
            for item in order.items
        )
        if risk == "Stock unavailable" and not shortages:
            continue
        if risk == "Low stock" and (shortages or not low_stock):
            continue
        if risk == "Credit review" and not order.credit_limit_exceeded:
            continue
        filtered.append(order)
    return filtered


def stock_shortages(order: Order) -> list[tuple[str, int, int]]:
    needed: dict[int, int] = defaultdict(int)
    for item in order.items:
        needed[item.product_id] += item.qty
    products = {i.product_id: i.product for i in order.items}
    return [
        (products[pid].name, qty, products[pid].stock)
        for pid, qty in needed.items()
        if products[pid].stock < qty
    ]


def approve_order(session: Session, order_id: int, admin_id: int, when: datetime | None = None) -> Order:
    actor = session.get(User, admin_id)
    if actor is None:
        raise OrderError("Approver not found.")
    try:
        require_action(actor.role, "order.approve")
    except PermissionError as exc:
        raise OrderError(str(exc)) from exc
    order = get_order(session, order_id)
    if order is None:
        raise OrderError("Order not found.")
    if order.status != STATUS_PENDING:
        raise OrderError(f"Order {order.order_no} is already {order.status.lower()}.")
    if order.required_approver_role == ROLE_ADMIN and actor.role != ROLE_ADMIN:
        raise OrderError("This order requires Admin / Owner approval.")

    shortages = stock_shortages(order)
    if shortages:
        raise InsufficientStockError(shortages)

    when = when or datetime.now()
    # Conditional updates guard against concurrent approvals and stock races.
    claimed = session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == STATUS_PENDING)
        .values(status=STATUS_APPROVED, decided_by_id=admin_id, decided_at=when)
    ).rowcount
    if claimed != 1:
        raise OrderError(f"Order {order.order_no} was already processed.")

    for item in order.items:
        try:
            inventory.record_movement(
                session,
                product_id=item.product_id,
                qty_delta=-item.qty,
                source_type="ORDER_APPROVAL",
                source_id=order.id,
                source_line_id=item.id,
                actor_id=admin_id,
                reason=f"Stock deducted on approval of {order.order_no}",
                occurred_at=when,
            )
        except ValueError as exc:
            product = session.get(Product, item.product_id)
            raise InsufficientStockError(
                [(product.name, item.qty, product.stock)]
            ) from exc

    session.expire_all()
    order = get_order(session, order_id)
    from erp.services.invoices import create_order_invoice

    create_order_invoice(
        session, order_id=order.id, actor_id=admin_id, invoice_date=when
    )
    notifications.notify(
        session, order.sales_person_id,
        f"Order {order.order_no} for {order.customer.name} was approved.", order.id,
    )
    audit.record(
        session, actor_id=admin_id, action="APPROVE", entity_type="ORDER",
        entity_id=order.id, changes={"status": STATUS_APPROVED},
    )
    return order


def reject_order(session: Session, order_id: int, admin_id: int, reason: str, when: datetime | None = None) -> Order:
    actor = session.get(User, admin_id)
    if actor is None:
        raise OrderError("Approver not found.")
    try:
        require_action(actor.role, "order.reject")
    except PermissionError as exc:
        raise OrderError(str(exc)) from exc
    reason = reason.strip()
    if not reason:
        raise OrderError("A rejection reason is required.")
    order = get_order(session, order_id)
    if order is None:
        raise OrderError("Order not found.")
    claimed = session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == STATUS_PENDING)
        .values(status=STATUS_REJECTED, decided_by_id=admin_id, decided_at=when or datetime.now(),
                rejection_reason=reason)
    ).rowcount
    if claimed != 1:
        raise OrderError(f"Order {order.order_no} is already {order.status.lower()}.")
    session.expire_all()
    order = get_order(session, order_id)
    notifications.notify(
        session, order.sales_person_id,
        f"Order {order.order_no} for {order.customer.name} was rejected: {reason}", order.id,
    )
    audit.record(
        session, actor_id=admin_id, action="REJECT", entity_type="ORDER",
        entity_id=order.id,
        changes={"status": STATUS_REJECTED, "reason": reason},
    )
    return order


def cancel_order(
    session: Session,
    order_id: int,
    actor_id: int,
    reason: str,
    when: datetime | None = None,
) -> Order:
    actor = session.get(User, actor_id)
    if actor is None:
        raise OrderError("User not found.")
    try:
        require_action(actor.role, "order.cancel")
    except PermissionError as exc:
        raise OrderError(str(exc)) from exc
    order = get_order(session, order_id)
    if order is None:
        raise OrderError("Order not found.")
    if actor.role == ROLE_SALES and order.sales_person_id != actor.id:
        raise OrderError("Sales executives can only cancel their own orders.")
    if order.status not in {STATUS_PENDING, STATUS_APPROVED}:
        raise OrderError("Only pending or approved orders can be cancelled.")
    reason = reason.strip()
    if not reason:
        raise OrderError("A cancellation reason is required.")
    existing_delivery = session.scalar(
        select(Delivery).where(Delivery.order_id == order.id).limit(1)
    )
    if existing_delivery:
        raise OrderError("Orders with deliveries cannot be cancelled.")

    when = when or datetime.now()
    if order.status == STATUS_APPROVED:
        from erp.models import SalesInvoice

        issued_invoice = session.scalar(
            select(SalesInvoice).where(SalesInvoice.order_id == order.id)
        )
        if issued_invoice:
            if issued_invoice.amount_paid or issued_invoice.credit_total:
                raise OrderError(
                    "An order with invoice payment or credit activity "
                    "cannot be cancelled."
                )
            issued_invoice.status = "CANCELLED"
            issued_invoice.cancelled_at = when or datetime.now()
            issued_invoice.cancellation_reason = f"Order cancelled: {reason}"
            issued_invoice.balance_due = Decimal("0")
        for item in order.items:
            try:
                inventory.record_movement(
                    session,
                    product_id=item.product_id,
                    qty_delta=item.qty,
                    source_type="ORDER_CANCELLATION",
                    source_id=order.id,
                    source_line_id=item.id,
                    actor_id=actor.id,
                    reason=f"Stock restored for cancelled order {order.order_no}",
                    occurred_at=when,
                )
            except ValueError as exc:
                raise OrderError(str(exc)) from exc
    order.status = STATUS_CANCELLED
    order.fulfillment_status = "CANCELLED"
    order.cancelled_by_id = actor.id
    order.cancelled_at = when
    order.cancellation_reason = reason
    notifications.notify(
        session, order.sales_person_id,
        f"Order {order.order_no} was cancelled: {reason}", order.id,
    )
    audit.record(
        session, actor_id=actor.id, action="CANCEL", entity_type="ORDER",
        entity_id=order.id, changes={"status": STATUS_CANCELLED, "reason": reason},
    )
    session.flush()
    return order
