from dataclasses import dataclass
from decimal import Decimal

from erp.services.discounts import discount_for, line_total, recommend


@dataclass
class T:
    min_qty: int
    discount_pct: Decimal


TIERS = [T(25, Decimal("10")), T(10, Decimal("5")), T(50, Decimal("15"))]


def test_discount_boundaries():
    assert discount_for(TIERS, 1) == 0
    assert discount_for(TIERS, 9) == 0
    assert discount_for(TIERS, 10) == 5
    assert discount_for(TIERS, 24) == 5
    assert discount_for(TIERS, 25) == 10
    assert discount_for(TIERS, 500) == 15
    assert discount_for([], 100) == 0


def test_line_total_rounding():
    assert line_total(Decimal("9.99"), 3, Decimal("5")) == Decimal("28.47")


def test_recommend_next_tier():
    rec = recommend(TIERS, Decimal("10"), 8)
    assert rec.next_min_qty == 10 and rec.extra_qty == 2 and rec.next_discount_pct == 5
    assert rec.current_line_total == Decimal("80.00")
    assert rec.next_line_total == Decimal("95.00")
    assert rec.extra_cost == Decimal("15.00")


def test_recommend_none_at_top():
    assert recommend(TIERS, Decimal("10"), 50) is None
    assert recommend([], Decimal("10"), 5) is None
