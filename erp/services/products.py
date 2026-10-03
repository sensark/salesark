from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from erp.models import (
    Customer,
    CustomerProductPrice,
    DiscountTier,
    PriceList,
    PriceListItem,
    Product,
    QuantityPriceTier,
    User,
)
from erp.permissions import require_action
from erp.services import audit, inventory


class ProductError(ValueError):
    pass


def list_products(session: Session, active_only: bool = True) -> list[Product]:
    stmt = select(Product).options(selectinload(Product.tiers)).order_by(Product.category, Product.name)
    if active_only:
        stmt = stmt.where(Product.active.is_(True))
    return list(session.scalars(stmt))


def get(session: Session, product_id: int) -> Product | None:
    return session.get(Product, product_id)


def save_product(
    session: Session,
    *,
    sku: str,
    name: str,
    category: str,
    unit_price: Decimal,
    stock: int,
    reorder_level: int,
    actor_id: int,
    unit: str = "EA",
    hsn_sac: str = "",
    gst_rate: Decimal = Decimal("0"),
    cess_rate: Decimal = Decimal("0"),
    cost_price: Decimal | None = None,
    active: bool = True,
    product_id: int | None = None,
) -> Product:
    sku, name, category = sku.strip().upper(), name.strip(), category.strip()
    if not sku or not name or not category:
        raise ProductError("SKU, name and category are required.")
    if unit_price <= 0:
        raise ProductError("Unit price must be greater than zero.")
    if stock < 0 or reorder_level < 0:
        raise ProductError("Stock and reorder level cannot be negative.")
    if gst_rate < 0 or gst_rate > 100 or cess_rate < 0 or cess_rate > 100:
        raise ProductError("GST and cess rates must be from 0 to 100 percent.")
    actor = session.get(User, actor_id)
    if actor is None:
        raise ProductError("Admin user not found.")
    try:
        require_action(actor.role, "product.manage")
    except PermissionError as exc:
        raise ProductError(str(exc)) from exc
    clash = session.scalar(select(Product).where(Product.sku == sku))
    if clash and clash.id != product_id:
        raise ProductError(f"SKU {sku} is already used by {clash.name}.")

    product = session.get(Product, product_id) if product_id else Product()
    previous_stock = product.stock if product_id else 0
    product.sku, product.name, product.category = sku, name, category
    product.unit_price, product.stock, product.reorder_level, product.active = (
        unit_price, previous_stock, reorder_level, active,
    )
    product.unit = unit.strip().upper() or "EA"
    product.hsn_sac = hsn_sac.strip() or None
    product.gst_rate = gst_rate
    product.cess_rate = cess_rate
    product.cost_price = cost_price
    session.add(product)
    session.flush()
    if stock != previous_stock:
        try:
            inventory.record_movement(
                session, product_id=product.id, qty_delta=stock - previous_stock,
                source_type="STOCK_ADJUSTMENT", source_id=product.id,
                source_line_id=None, actor_id=actor.id,
                reason="Product catalog stock adjustment",
            )
        except ValueError as exc:
            raise ProductError(str(exc)) from exc
    audit.record(
        session, actor_id=actor.id, action="SAVE", entity_type="PRODUCT",
        entity_id=product.id, changes={"sku": sku, "unit_price": unit_price,
                                       "stock": stock, "gst_rate": gst_rate},
    )
    return product


def replace_tiers(
    session: Session,
    product_id: int,
    tiers: list[tuple[int, Decimal]],
    actor_id: int,
) -> None:
    seen: set[int] = set()
    for min_qty, pct in tiers:
        if min_qty < 1:
            raise ProductError("Tier minimum quantity must be at least 1.")
        if not (Decimal("0") < pct < Decimal("100")):
            raise ProductError("Discount must be between 0 and 100 percent.")
        if min_qty in seen:
            raise ProductError(f"Duplicate tier for quantity {min_qty}.")
        seen.add(min_qty)
    product = session.get(Product, product_id)
    if product is None:
        raise ProductError("Product not found.")
    actor = session.get(User, actor_id)
    if actor is None:
        raise ProductError("Admin user not found.")
    try:
        require_action(actor.role, "discount.manage")
    except PermissionError as exc:
        raise ProductError(str(exc)) from exc
    product.tiers.clear()
    session.flush()
    for min_qty, pct in sorted(tiers):
        product.tiers.append(DiscountTier(min_qty=min_qty, discount_pct=pct))
    session.flush()
    audit.record(
        session, actor_id=actor.id, action="REPLACE", entity_type="DISCOUNT_TIERS",
        entity_id=product.id, changes={"tiers": tiers},
    )


def save_price_list_item(
    session: Session,
    *,
    actor_id: int,
    price_list_id: int,
    product_id: int,
    unit_price: Decimal,
) -> PriceListItem:
    actor = session.get(User, actor_id)
    if actor is None:
        raise ProductError("Admin user not found.")
    try:
        require_action(actor.role, "price.manage")
    except PermissionError as exc:
        raise ProductError(str(exc)) from exc
    if unit_price <= 0:
        raise ProductError("Price must be greater than zero.")
    if session.get(PriceList, price_list_id) is None or session.get(Product, product_id) is None:
        raise ProductError("Choose an existing price list and product.")
    row = session.scalar(select(PriceListItem).where(
        PriceListItem.price_list_id == price_list_id,
        PriceListItem.product_id == product_id,
    ))
    if row is None:
        row = PriceListItem(price_list_id=price_list_id, product_id=product_id, unit_price=unit_price)
    else:
        row.unit_price = unit_price
    session.add(row)
    session.flush()
    audit.record(session, actor_id=actor.id, action="SAVE", entity_type="PRICE_LIST_ITEM",
                 entity_id=row.id, changes={"price_list_id": price_list_id,
                                            "product_id": product_id, "unit_price": unit_price})
    return row


def save_customer_price(
    session: Session,
    *,
    actor_id: int,
    customer_id: int,
    product_id: int,
    unit_price: Decimal,
    active: bool = True,
) -> CustomerProductPrice:
    actor = session.get(User, actor_id)
    if actor is None:
        raise ProductError("Admin user not found.")
    try:
        require_action(actor.role, "price.manage")
    except PermissionError as exc:
        raise ProductError(str(exc)) from exc
    if unit_price <= 0:
        raise ProductError("Price must be greater than zero.")
    if session.get(Customer, customer_id) is None or session.get(Product, product_id) is None:
        raise ProductError("Choose an existing customer and product.")
    row = session.scalar(select(CustomerProductPrice).where(
        CustomerProductPrice.customer_id == customer_id,
        CustomerProductPrice.product_id == product_id,
    ))
    if row is None:
        row = CustomerProductPrice(
            customer_id=customer_id, product_id=product_id,
            unit_price=unit_price, active=active,
        )
    else:
        row.unit_price = unit_price
        row.active = active
    session.add(row)
    session.flush()
    audit.record(session, actor_id=actor.id, action="SAVE", entity_type="CUSTOMER_PRODUCT_PRICE",
                 entity_id=row.id, changes={"customer_id": customer_id,
                                            "product_id": product_id, "unit_price": unit_price,
                                            "active": active})
    return row


def replace_quantity_prices(
    session: Session,
    *,
    actor_id: int,
    product_id: int,
    tiers: list[tuple[int, Decimal]],
) -> None:
    actor = session.get(User, actor_id)
    if actor is None:
        raise ProductError("Admin user not found.")
    try:
        require_action(actor.role, "price.manage")
    except PermissionError as exc:
        raise ProductError(str(exc)) from exc
    if any(qty < 1 or price <= 0 for qty, price in tiers):
        raise ProductError("Quantity thresholds and prices must be greater than zero.")
    quantities = [qty for qty, _ in tiers]
    if len(set(quantities)) != len(quantities):
        raise ProductError("Quantity thresholds must be unique.")
    product = session.get(Product, product_id)
    if product is None:
        raise ProductError("Product not found.")
    session.query(QuantityPriceTier).filter_by(product_id=product_id).delete()
    for min_qty, unit_price in sorted(tiers):
        session.add(QuantityPriceTier(product_id=product_id, min_qty=min_qty, unit_price=unit_price))
    session.flush()
    audit.record(session, actor_id=actor.id, action="REPLACE", entity_type="QUANTITY_PRICE_TIERS",
                 entity_id=product_id, changes={"tiers": tiers})
