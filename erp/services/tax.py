from dataclasses import dataclass
from decimal import Decimal

from erp.services.discounts import money

ZERO = Decimal("0")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class TaxBreakdown:
    gross: Decimal
    discount: Decimal
    taxable: Decimal
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    cess_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    total_tax: Decimal
    total: Decimal


def calculate_gst(
    *,
    unit_price: Decimal,
    qty: int,
    discount_pct: Decimal = ZERO,
    gst_rate: Decimal = ZERO,
    cess_rate: Decimal = ZERO,
    supplier_state: str,
    place_of_supply_state: str,
    supply_type: str = "DOMESTIC",
) -> TaxBreakdown:
    if qty <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if unit_price < 0 or not (ZERO <= discount_pct < HUNDRED):
        raise ValueError("Price must be nonnegative and discount must be from 0 to 100 percent.")
    if not (ZERO <= gst_rate <= HUNDRED and ZERO <= cess_rate <= HUNDRED):
        raise ValueError("GST and cess rates must be from 0 to 100 percent.")

    gross = money(unit_price * qty)
    taxable = money(gross * (HUNDRED - discount_pct) / HUNDRED)
    discount = gross - taxable
    is_export = supply_type.upper() == "EXPORT"
    same_state = supplier_state.strip().casefold() == place_of_supply_state.strip().casefold()

    cgst_rate = sgst_rate = igst_rate = ZERO
    if is_export:
        applied_cess = ZERO
    elif same_state:
        cgst_rate = sgst_rate = Decimal(gst_rate) / 2
        applied_cess = cess_rate
    else:
        igst_rate = Decimal(gst_rate)
        applied_cess = cess_rate

    cgst = money(taxable * cgst_rate / HUNDRED)
    sgst = money(taxable * sgst_rate / HUNDRED)
    igst = money(taxable * igst_rate / HUNDRED)
    cess = money(taxable * applied_cess / HUNDRED)
    total_tax = cgst + sgst + igst + cess
    return TaxBreakdown(
        gross=gross,
        discount=discount,
        taxable=taxable,
        cgst_rate=cgst_rate,
        sgst_rate=sgst_rate,
        igst_rate=igst_rate,
        cess_rate=applied_cess,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        cess=cess,
        total_tax=total_tax,
        total=taxable + total_tax,
    )
