from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.models import (
    CustomerProductPrice,
    PriceList,
    PriceListItem,
    Product,
    QuantityPriceTier,
)


@dataclass(frozen=True)
class PriceResolution:
    unit_price: Decimal
    source: str


def resolve_unit_price(
    session: Session,
    product: Product,
    qty: int,
    *,
    customer_id: int | None = None,
    price_list_id: int | None = None,
    at: datetime | None = None,
) -> PriceResolution:
    if qty < 1:
        raise ValueError("Quantity must be greater than zero.")
    at = at or datetime.now()

    if customer_id is not None:
        customer_price = session.scalar(
            select(CustomerProductPrice).where(
                CustomerProductPrice.customer_id == customer_id,
                CustomerProductPrice.product_id == product.id,
                CustomerProductPrice.active.is_(True),
                (CustomerProductPrice.valid_from.is_(None) | (CustomerProductPrice.valid_from <= at)),
                (CustomerProductPrice.valid_until.is_(None) | (CustomerProductPrice.valid_until >= at)),
            )
        )
        if customer_price:
            return PriceResolution(customer_price.unit_price, "customer")

    if price_list_id is not None:
        price_list = session.get(PriceList, price_list_id)
        if (
            price_list
            and price_list.active
            and (price_list.valid_from is None or price_list.valid_from <= at)
            and (price_list.valid_until is None or price_list.valid_until >= at)
        ):
            listed = session.scalar(
                select(PriceListItem).where(
                    PriceListItem.price_list_id == price_list_id,
                    PriceListItem.product_id == product.id,
                )
            )
            if listed:
                return PriceResolution(listed.unit_price, "price_list")

    tier = session.scalar(
        select(QuantityPriceTier)
        .where(QuantityPriceTier.product_id == product.id, QuantityPriceTier.min_qty <= qty)
        .order_by(QuantityPriceTier.min_qty.desc())
        .limit(1)
    )
    if tier:
        return PriceResolution(tier.unit_price, "quantity")
    return PriceResolution(product.unit_price, "standard")
