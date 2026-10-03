import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from erp.models import ROLE_ADMIN, ROLE_SALES, Base, Customer, DiscountTier, Product, User  # noqa: E402


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture
def data(session):
    admin = User(username="admin", name="Admin", email="a@example.com", password_hash="x", role=ROLE_ADMIN)
    sales = User(username="sp", name="Sales", email="s@example.com", password_hash="x", role=ROLE_SALES)
    session.add_all([admin, sales])
    session.flush()
    customer = Customer(name="Cust", email="c@example.com", region="North", created_by_id=sales.id)
    pen = Product(sku="PEN", name="Pen", category="Office", unit_price=Decimal("10.00"), stock=100, reorder_level=10)
    pen.tiers = [DiscountTier(min_qty=10, discount_pct=Decimal("5")), DiscountTier(min_qty=25, discount_pct=Decimal("10"))]
    desk = Product(sku="DESK", name="Desk", category="Furniture", unit_price=Decimal("500.00"), stock=3, reorder_level=2)
    session.add_all([customer, pen, desk])
    session.commit()
    return {"admin": admin, "sales": sales, "customer": customer, "pen": pen, "desk": desk}
