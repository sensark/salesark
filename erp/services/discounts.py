from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Protocol

CENT = Decimal("0.01")


class TierLike(Protocol):
    min_qty: int
    discount_pct: Decimal


@dataclass(frozen=True)
class Recommendation:
    next_min_qty: int
    next_discount_pct: Decimal
    extra_qty: int
    current_line_total: Decimal
    next_line_total: Decimal

    @property
    def extra_cost(self) -> Decimal:
        return self.next_line_total - self.current_line_total

    @property
    def message(self) -> str:
        return (
            f"Add {self.extra_qty} more to reach {self.next_min_qty} units "
            f"and unlock {self.next_discount_pct:.0f}% off"
        )


def money(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _sorted(tiers: Iterable[TierLike]) -> list[TierLike]:
    return sorted(tiers, key=lambda t: t.min_qty)


def discount_for(tiers: Iterable[TierLike], qty: int) -> Decimal:
    """Best discount percentage the quantity qualifies for."""
    pct = Decimal("0")
    for tier in _sorted(tiers):
        if qty >= tier.min_qty:
            pct = max(pct, Decimal(tier.discount_pct))
    return pct


def line_total(unit_price: Decimal, qty: int, discount_pct: Decimal) -> Decimal:
    gross = Decimal(unit_price) * qty
    return money(gross * (Decimal("100") - Decimal(discount_pct)) / Decimal("100"))


def recommend(tiers: Iterable[TierLike], unit_price: Decimal, qty: int) -> Recommendation | None:
    """Next tier above the current quantity, or None if already at the top tier."""
    current_pct = discount_for(tiers, qty)
    for tier in _sorted(tiers):
        if tier.min_qty > qty and Decimal(tier.discount_pct) > current_pct:
            return Recommendation(
                next_min_qty=tier.min_qty,
                next_discount_pct=Decimal(tier.discount_pct),
                extra_qty=tier.min_qty - qty,
                current_line_total=line_total(unit_price, qty, current_pct),
                next_line_total=line_total(unit_price, tier.min_qty, Decimal(tier.discount_pct)),
            )
    return None
