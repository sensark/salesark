from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.models import SalesInvoice


def outstanding(session: Session, customer_id: int) -> Decimal:
    value = session.scalar(
        select(func.coalesce(func.sum(SalesInvoice.balance_due), 0)).where(
            SalesInvoice.customer_id == customer_id,
            SalesInvoice.status.in_(["ISSUED", "PARTIALLY_PAID"]),
        )
    )
    return Decimal(value or 0)


def review_required(
    session: Session,
    *,
    customer_id: int,
    credit_limit: Decimal,
    order_total: Decimal,
) -> bool:
    if credit_limit <= 0:
        return False
    return outstanding(session, customer_id) + order_total > credit_limit