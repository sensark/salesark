"""Leakage-safe feature builders: every function only uses rows dated before `as_of`."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp.models import (
    STATUS_APPROVED,
    Customer,
    Order,
    OrderItem,
    Payment,
    PaymentAllocation,
    Quotation,
    QuotationItem,
    SalesInvoice,
    SalesReturn,
)

HORIZON_DAYS = 90
PAYMENT_GRACE_DAYS = 7
OPEN_QUOTE_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "SENT")
LOST_QUOTE_STATUSES = ("REJECTED", "EXPIRED", "CANCELLED")

CUSTOMER_FEATURES = [
    "recency_days", "frequency", "monetary_log", "orders_90d", "orders_prev_90d",
    "revenue_trend", "avg_order_log", "avg_gap_days", "gap_ratio", "tenure_days",
    "avg_discount_pct", "return_count", "avg_days_late",
]


def _frame(session: Session, stmt) -> pd.DataFrame:
    return pd.DataFrame(session.execute(stmt).mappings().all())


def load_orders(session: Session) -> pd.DataFrame:
    df = _frame(session, select(
        Order.id.label("order_id"), Order.customer_id, Order.sales_person_id, Order.created_at,
        Order.subtotal, Order.discount_total, Order.total,
    ).where(Order.status == STATUS_APPROVED))
    if df.empty:
        return pd.DataFrame(columns=["order_id", "customer_id", "sales_person_id", "created_at",
                                     "subtotal", "discount_total", "total"])
    for col in ("subtotal", "discount_total", "total"):
        df[col] = df[col].astype(float)
    df["created_at"] = pd.to_datetime(df["created_at"])
    return df


def load_items(session: Session) -> pd.DataFrame:
    df = _frame(session, select(
        OrderItem.product_id, OrderItem.qty, Order.created_at,
    ).join(Order, Order.id == OrderItem.order_id).where(Order.status == STATUS_APPROVED))
    if df.empty:
        return pd.DataFrame(columns=["product_id", "qty", "created_at"])
    df["created_at"] = pd.to_datetime(df["created_at"])
    return df


def load_returns(session: Session) -> pd.DataFrame:
    df = _frame(session, select(SalesReturn.customer_id, SalesReturn.created_at))
    if df.empty:
        return pd.DataFrame(columns=["customer_id", "created_at"])
    df["created_at"] = pd.to_datetime(df["created_at"])
    return df


def load_invoices(session: Session) -> pd.DataFrame:
    paid_at = (
        select(PaymentAllocation.invoice_id, func.max(Payment.payment_date).label("last_payment_at"))
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .group_by(PaymentAllocation.invoice_id)
        .subquery()
    )
    df = _frame(session, select(
        SalesInvoice.id.label("invoice_id"), SalesInvoice.customer_id, SalesInvoice.status,
        SalesInvoice.invoice_date, SalesInvoice.due_date, SalesInvoice.total,
        SalesInvoice.balance_due, Customer.credit_limit, Customer.credit_period_days,
        paid_at.c.last_payment_at,
    ).join(Customer, Customer.id == SalesInvoice.customer_id)
     .outerjoin(paid_at, paid_at.c.invoice_id == SalesInvoice.id)
     .where(SalesInvoice.status.in_(["ISSUED", "PARTIALLY_PAID", "PAID"])))
    if df.empty:
        return pd.DataFrame(columns=["invoice_id", "customer_id", "status", "invoice_date", "due_date",
                                     "total", "balance_due", "credit_limit", "credit_period_days",
                                     "last_payment_at", "paid_at"])
    for col in ("total", "balance_due", "credit_limit"):
        df[col] = df[col].astype(float)
    for col in ("invoice_date", "due_date", "last_payment_at"):
        df[col] = pd.to_datetime(df[col])
    df["due_date"] = df["due_date"].fillna(df["invoice_date"])
    df["paid_at"] = df["last_payment_at"].where(df["balance_due"] <= 0.005)
    return df


def load_quotations(session: Session) -> pd.DataFrame:
    n_items = (
        select(QuotationItem.quotation_id, func.count().label("n_items"))
        .group_by(QuotationItem.quotation_id).subquery()
    )
    df = _frame(session, select(
        Quotation.id.label("quotation_id"), Quotation.quotation_no, Quotation.customer_id,
        Quotation.sales_person_id, Quotation.status, Quotation.subtotal, Quotation.discount_total,
        Quotation.total, Quotation.valid_until, Quotation.created_at, Quotation.converted_order_id,
        Quotation.decided_at, Quotation.accepted_at,
        func.coalesce(n_items.c.n_items, 0).label("n_items"),
    ).outerjoin(n_items, n_items.c.quotation_id == Quotation.id))
    if df.empty:
        return df
    for col in ("subtotal", "discount_total", "total"):
        df[col] = df[col].astype(float)
    for col in ("created_at", "valid_until", "decided_at", "accepted_at"):
        df[col] = pd.to_datetime(df[col])
    return df


def _days_late(invoices: pd.DataFrame, as_of: datetime) -> pd.Series:
    """Average days paid after due date, for invoices already settled or overdue at `as_of`."""
    if invoices.empty:
        return pd.Series(dtype=float)
    inv = invoices[invoices["due_date"] < as_of]
    settled = inv["paid_at"].where(inv["paid_at"] < as_of)
    late = (settled.fillna(pd.Timestamp(as_of)) - inv["due_date"]).dt.days.clip(lower=0)
    return late.groupby(inv["customer_id"]).mean()


def customer_features(
    orders: pd.DataFrame,
    returns: pd.DataFrame,
    invoices: pd.DataFrame,
    as_of: datetime,
) -> pd.DataFrame:
    """One row per customer with at least one approved order before `as_of`."""
    as_of = pd.Timestamp(as_of)
    hist = orders[orders["created_at"] < as_of]
    if hist.empty:
        return pd.DataFrame(columns=CUSTOMER_FEATURES)
    g = hist.groupby("customer_id")
    first, last = g["created_at"].min(), g["created_at"].max()
    feats = pd.DataFrame({
        "recency_days": (as_of - last).dt.days,
        "frequency": g.size(),
        "monetary": g["total"].sum(),
        "tenure_days": (as_of - first).dt.days,
        "avg_discount_pct": g["discount_total"].sum() / g["subtotal"].sum().replace(0, np.nan) * 100,
    })
    recent = hist[hist["created_at"] >= as_of - timedelta(days=HORIZON_DAYS)]
    prev = hist[(hist["created_at"] < as_of - timedelta(days=HORIZON_DAYS))
                & (hist["created_at"] >= as_of - timedelta(days=2 * HORIZON_DAYS))]
    feats["orders_90d"] = recent.groupby("customer_id").size()
    feats["orders_prev_90d"] = prev.groupby("customer_id").size()
    feats["revenue_90d"] = recent.groupby("customer_id")["total"].sum()
    feats["revenue_prev_90d"] = prev.groupby("customer_id")["total"].sum()
    feats = feats.fillna({"orders_90d": 0, "orders_prev_90d": 0, "revenue_90d": 0.0,
                          "revenue_prev_90d": 0.0, "avg_discount_pct": 0.0})
    feats["revenue_trend"] = (feats["revenue_90d"] - feats["revenue_prev_90d"]) / (
        feats["revenue_90d"] + feats["revenue_prev_90d"] + 1.0)
    feats["avg_order_log"] = np.log1p(feats["monetary"] / feats["frequency"])
    feats["monetary_log"] = np.log1p(feats["monetary"])
    feats["avg_gap_days"] = (feats["tenure_days"] - feats["recency_days"]) / (feats["frequency"] - 1).clip(lower=1)
    feats.loc[feats["frequency"] <= 1, "avg_gap_days"] = feats["tenure_days"]
    feats["gap_ratio"] = feats["recency_days"] / feats["avg_gap_days"].clip(lower=1)
    ret = returns[returns["created_at"] < as_of]
    feats["return_count"] = ret.groupby("customer_id").size().reindex(feats.index).fillna(0)
    feats["avg_days_late"] = _days_late(invoices, as_of).reindex(feats.index).fillna(0.0)
    return feats.astype(float)


def future_revenue(orders: pd.DataFrame, as_of: datetime, days: int = HORIZON_DAYS) -> pd.Series:
    as_of = pd.Timestamp(as_of)
    window = orders[(orders["created_at"] >= as_of) & (orders["created_at"] < as_of + timedelta(days=days))]
    return window.groupby("customer_id")["total"].sum()


def snapshot_dates(orders: pd.DataFrame, now: datetime, step_days: int = 30, warmup_days: int = 120) -> list[datetime]:
    """Monthly training cutoffs whose full label horizon lies before `now`."""
    if orders.empty:
        return []
    start = orders["created_at"].min() + timedelta(days=warmup_days)
    last = pd.Timestamp(now) - timedelta(days=HORIZON_DAYS)
    dates = []
    cursor = last
    while cursor >= start:
        dates.append(cursor.to_pydatetime())
        cursor -= timedelta(days=step_days)
    return sorted(dates)


def customer_training_set(
    orders: pd.DataFrame, returns: pd.DataFrame, invoices: pd.DataFrame, now: datetime,
) -> pd.DataFrame:
    """Stacked monthly snapshots labelled with the following 90 days of behaviour."""
    frames = []
    for cutoff in snapshot_dates(orders, now):
        feats = customer_features(orders, returns, invoices, cutoff)
        if feats.empty:
            continue
        fut = future_revenue(orders, cutoff).reindex(feats.index).fillna(0.0)
        frames.append(feats.assign(cutoff=cutoff, future_revenue=fut, churned=(fut <= 0).astype(int)))
    if not frames:
        return pd.DataFrame(columns=CUSTOMER_FEATURES + ["cutoff", "future_revenue", "churned"])
    return pd.concat(frames)


def backtest_split(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Test on the latest cutoff; train only on cutoffs whose label window ends before it."""
    test_cutoff = train["cutoff"].max()
    fit = train[train["cutoff"] <= test_cutoff - timedelta(days=HORIZON_DAYS)]
    return fit, train[train["cutoff"] == test_cutoff]


def weekly_demand(items: pd.DataFrame, product_ids: list[int], now: datetime, weeks: int = 52) -> pd.DataFrame:
    """Units sold per product per week (columns = product_id), zero-filled, ending the week before `now`."""
    end = pd.Timestamp(now).normalize()
    start = end - timedelta(weeks=weeks)
    index = pd.date_range(start, periods=weeks, freq="7D")
    hist = items[(items["created_at"] >= start) & (items["created_at"] < end)]
    if hist.empty:
        return pd.DataFrame(0.0, index=index, columns=product_ids)
    bucket = ((hist["created_at"] - start).dt.days // 7).clip(upper=weeks - 1)
    table = hist.assign(week=bucket).pivot_table(index="week", columns="product_id", values="qty",
                                                 aggfunc="sum", fill_value=0)
    table = table.reindex(index=range(weeks), columns=product_ids, fill_value=0).astype(float)
    table.index = index
    return table
