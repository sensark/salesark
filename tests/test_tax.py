from decimal import Decimal

import pytest

from erp.services.tax import calculate_gst


def calc(**overrides):
    values = dict(
        unit_price=Decimal("1000"), qty=1, discount_pct=Decimal("5"),
        gst_rate=Decimal("18"), cess_rate=Decimal("1"),
        supplier_state="West Bengal", place_of_supply_state="West Bengal",
    )
    values.update(overrides)
    return calculate_gst(**values)


def test_intra_state_splits_cgst_sgst_after_discount():
    tax = calc()
    assert tax.gross == Decimal("1000.00")
    assert tax.discount == Decimal("50.00")
    assert tax.taxable == Decimal("950.00")
    assert tax.cgst == Decimal("85.50")
    assert tax.sgst == Decimal("85.50")
    assert tax.igst == Decimal("0.00")
    assert tax.cess == Decimal("9.50")
    assert tax.total == Decimal("1130.50")


def test_inter_state_uses_igst():
    tax = calc(place_of_supply_state="Maharashtra")
    assert tax.cgst == Decimal("0.00")
    assert tax.sgst == Decimal("0.00")
    assert tax.igst == Decimal("171.00")
    assert tax.total == Decimal("1130.50")


def test_export_zero_rates_gst_and_cess():
    tax = calc(supply_type="EXPORT", place_of_supply_state="Germany")
    assert tax.taxable == Decimal("950.00")
    assert tax.total_tax == Decimal("0.00")
    assert tax.total == Decimal("950.00")


def test_tax_rounds_half_up():
    tax = calc(unit_price=Decimal("0.05"), qty=1, discount_pct=Decimal("0"),
               gst_rate=Decimal("5"), cess_rate=Decimal("0"))
    assert tax.cgst == Decimal("0.00")
    assert tax.sgst == Decimal("0.00")
    assert tax.total == Decimal("0.05")


@pytest.mark.parametrize("kwargs", [
    {"qty": 0}, {"unit_price": Decimal("-1")}, {"discount_pct": Decimal("100")},
    {"gst_rate": Decimal("101")}, {"cess_rate": Decimal("-1")},
])
def test_rejects_invalid_tax_inputs(kwargs):
    with pytest.raises(ValueError):
        calc(**kwargs)
