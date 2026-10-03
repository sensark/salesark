from datetime import datetime, timedelta
from decimal import Decimal

from erp.models import CustomerProductPrice, PriceList, PriceListItem, QuantityPriceTier
from erp.services.pricing import resolve_unit_price


def test_price_precedence_customer_then_list_then_qty_then_standard(session, data):
    product = data["pen"]
    customer = data["customer"]
    customer.price_list_id = None
    price_list = PriceList(name="Dealer", active=True)
    session.add(price_list)
    session.flush()
    session.add_all([
        PriceListItem(price_list_id=price_list.id, product_id=product.id, unit_price=Decimal("8.00")),
        QuantityPriceTier(product_id=product.id, min_qty=10, unit_price=Decimal("9.00")),
    ])
    session.flush()

    resolved = resolve_unit_price(session, product, 12, customer_id=customer.id, price_list_id=price_list.id)
    assert (resolved.unit_price, resolved.source) == (Decimal("8.00"), "price_list")

    customer_price = CustomerProductPrice(customer_id=customer.id, product_id=product.id,
                                          unit_price=Decimal("7.00"), active=True)
    session.add(customer_price)
    session.flush()
    resolved = resolve_unit_price(session, product, 12, customer_id=customer.id, price_list_id=price_list.id)
    assert (resolved.unit_price, resolved.source) == (Decimal("7.00"), "customer")

    resolved = resolve_unit_price(session, product, 12)
    assert (resolved.unit_price, resolved.source) == (Decimal("9.00"), "quantity")

    resolved = resolve_unit_price(session, product, 2)
    assert (resolved.unit_price, resolved.source) == (Decimal("10.00"), "standard")


def test_expired_customer_price_falls_through(session, data):
    product = data["pen"]
    session.add(CustomerProductPrice(
        customer_id=data["customer"].id, product_id=product.id, unit_price=Decimal("1.00"),
        active=True, valid_until=datetime.now() - timedelta(days=1),
    ))
    session.flush()
    resolved = resolve_unit_price(session, product, 1, customer_id=data["customer"].id)
    assert resolved.source == "standard" and resolved.unit_price == Decimal("10.00")
