from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from erp.models import DocumentSeries

DEFAULT_SERIES = {
    "QUOTATION": "QT",
    "ORDER": "SO",
    "DELIVERY": "DN",
    "INVOICE": "INV",
    "CREDIT_NOTE": "CN",
    "DEBIT_NOTE": "DBN",
    "PAYMENT": "RCPT",
    "RETURN": "SR",
}


def fiscal_year(value: datetime, start_month: int = 4) -> str:
    start_year = value.year if value.month >= start_month else value.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def next_document_number(session: Session, document_type: str, at: datetime | None = None) -> str:
    at = at or datetime.now()
    series = session.scalar(
        select(DocumentSeries).where(DocumentSeries.document_type == document_type).with_for_update()
    )
    if series is None:
        prefix = DEFAULT_SERIES.get(document_type)
        if prefix is None:
            raise ValueError(f"No number series configured for {document_type}.")
        series = DocumentSeries(document_type=document_type, prefix=prefix, next_number=1)
        session.add(series)
        session.flush()

    allocated = series.next_number
    updated = session.execute(
        update(DocumentSeries)
        .where(DocumentSeries.id == series.id, DocumentSeries.next_number == allocated)
        .values(next_number=allocated + 1)
    ).rowcount
    if updated != 1:
        session.refresh(series)
        return next_document_number(session, document_type, at)
    return f"{series.prefix}-{fiscal_year(at, series.fiscal_year_start_month)}-{allocated:0{series.padding}d}"
