from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.models import Customer, Order, OrderItem, Product, User


def orders_frame(session: Session) -> pd.DataFrame:
    stmt = (
        select(
            Order.id.label("order_id"),
            Order.order_no,
            Order.status,
            Order.created_at,
            Order.decided_at,
            Order.subtotal,
            Order.discount_total,
            Order.total,
            Customer.id.label("customer_id"),
            Customer.name.label("customer"),
            Customer.company,
            Customer.region,
            User.id.label("sales_person_id"),
            User.name.label("sales_person"),
        )
        .join(Customer, Customer.id == Order.customer_id)
        .join(User, User.id == Order.sales_person_id)
    )
    df = pd.DataFrame(session.execute(stmt).mappings().all())
    if df.empty:
        return df
    for col in ("subtotal", "discount_total", "total"):
        df[col] = df[col].astype(float)
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["decided_at"] = pd.to_datetime(df["decided_at"])
    return df


def items_frame(session: Session) -> pd.DataFrame:
    stmt = (
        select(
            OrderItem.order_id,
            OrderItem.qty,
            OrderItem.unit_price,
            OrderItem.discount_pct,
            OrderItem.line_total,
            Product.id.label("product_id"),
            Product.name.label("product"),
            Product.category,
        )
        .join(Product, Product.id == OrderItem.product_id)
    )
    df = pd.DataFrame(session.execute(stmt).mappings().all())
    if df.empty:
        return df
    for col in ("unit_price", "discount_pct", "line_total"):
        df[col] = df[col].astype(float)
    df["gross"] = df["unit_price"] * df["qty"]
    df["discount_amount"] = df["gross"] - df["line_total"]
    return df


def filter_orders(
    df: pd.DataFrame,
    start: date,
    end: date,
    regions: list[str] | None = None,
    sales_people: list[str] | None = None,
) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (df["created_at"].dt.date >= start) & (df["created_at"].dt.date <= end)
    if regions:
        mask &= df["region"].isin(regions)
    if sales_people:
        mask &= df["sales_person"].isin(sales_people)
    return df[mask]


def kpis(orders: pd.DataFrame) -> dict:
    approved = orders[orders["status"] == "APPROVED"] if not orders.empty else orders
    decided = orders[orders["status"] != "PENDING"] if not orders.empty else orders
    revenue = float(approved["total"].sum()) if not approved.empty else 0.0
    return {
        "revenue": revenue,
        "orders": int(len(approved)),
        "avg_order": revenue / len(approved) if len(approved) else 0.0,
        "discount": float(approved["discount_total"].sum()) if not approved.empty else 0.0,
        "customers": int(approved["customer_id"].nunique()) if not approved.empty else 0,
        "pending": int((orders["status"] == "PENDING").sum()) if not orders.empty else 0,
        "approval_rate": (
            float((decided["status"] == "APPROVED").mean()) if len(decided) else 0.0
        ),
    }


def monthly_revenue(approved: pd.DataFrame) -> pd.DataFrame:
    if approved.empty:
        return pd.DataFrame(columns=["month", "revenue", "orders", "discount"])
    return (
        approved.assign(month=approved["created_at"].dt.to_period("M").dt.to_timestamp())
        .groupby("month")
        .agg(revenue=("total", "sum"), orders=("order_id", "count"), discount=("discount_total", "sum"))
        .reset_index()
    )


def leaderboard(orders: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame()
    g = orders.groupby("sales_person")
    board = pd.DataFrame({
        "revenue": g.apply(lambda d: d.loc[d["status"] == "APPROVED", "total"].sum(), include_groups=False),
        "approved_orders": g.apply(lambda d: (d["status"] == "APPROVED").sum(), include_groups=False),
        "rejected_orders": g.apply(lambda d: (d["status"] == "REJECTED").sum(), include_groups=False),
        "pending_orders": g.apply(lambda d: (d["status"] == "PENDING").sum(), include_groups=False),
        "customers": g.apply(lambda d: d.loc[d["status"] == "APPROVED", "customer_id"].nunique(), include_groups=False),
        "discount_given": g.apply(lambda d: d.loc[d["status"] == "APPROVED", "discount_total"].sum(), include_groups=False),
    })
    decided = board["approved_orders"] + board["rejected_orders"]
    board["approval_rate"] = (board["approved_orders"] / decided.where(decided > 0)).fillna(0)
    board["avg_order"] = (board["revenue"] / board["approved_orders"].where(board["approved_orders"] > 0)).fillna(0)
    return board.sort_values("revenue", ascending=False).reset_index()


def approved_items(approved: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    if approved.empty or items.empty:
        return pd.DataFrame()
    return items.merge(approved[["order_id", "created_at", "region", "sales_person"]], on="order_id")


def top_products(items: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    if items.empty:
        return pd.DataFrame()
    return (
        items.groupby(["product", "category"])
        .agg(revenue=("line_total", "sum"), units=("qty", "sum"))
        .reset_index()
        .sort_values("revenue", ascending=False)
        .head(n)
    )


def category_revenue(items: pd.DataFrame) -> pd.DataFrame:
    if items.empty:
        return pd.DataFrame()
    return items.groupby("category").agg(revenue=("line_total", "sum"), units=("qty", "sum")).reset_index()


def top_customers(approved: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    if approved.empty:
        return pd.DataFrame()
    return (
        approved.groupby(["customer", "company", "region"], dropna=False)
        .agg(revenue=("total", "sum"), orders=("order_id", "count"))
        .reset_index()
        .sort_values("revenue", ascending=False)
        .head(n)
    )


def pareto_products(items: pd.DataFrame) -> pd.DataFrame:
    if items.empty:
        return pd.DataFrame()
    summary = items.groupby(["product", "category"], dropna=False).agg(
        revenue=("line_total", "sum"), units=("qty", "sum")
    ).reset_index().sort_values("revenue", ascending=False)
    summary["revenue_share"] = summary["revenue"] / summary["revenue"].sum()
    summary["cumulative_revenue_share"] = summary["revenue_share"].cumsum()
    return summary


def pareto_customers(approved: pd.DataFrame) -> pd.DataFrame:
    if approved.empty:
        return pd.DataFrame()
    summary = approved.groupby(
        ["customer", "company", "region"], dropna=False
    ).agg(revenue=("total", "sum"), orders=("order_id", "count")).reset_index()
    summary = summary.sort_values("revenue", ascending=False)
    summary["revenue_share"] = summary["revenue"] / summary["revenue"].sum()
    summary["cumulative_revenue_share"] = summary["revenue_share"].cumsum()
    return summary


def region_revenue(approved: pd.DataFrame) -> pd.DataFrame:
    if approved.empty:
        return pd.DataFrame()
    return (
        approved.groupby("region")
        .agg(revenue=("total", "sum"), orders=("order_id", "count"), customers=("customer_id", "nunique"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )


def discount_bands(items: pd.DataFrame) -> pd.DataFrame:
    if items.empty:
        return pd.DataFrame()
    bands = items.assign(band=items["discount_pct"].map(lambda p: "No discount" if p == 0 else f"{p:.0f}%"))
    out = (
        bands.groupby("band")
        .agg(lines=("qty", "count"), units=("qty", "sum"), revenue=("line_total", "sum"),
             discount=("discount_amount", "sum"), avg_units=("qty", "mean"))
        .reset_index()
    )
    out["sort"] = out["band"].map(lambda b: -1 if b == "No discount" else float(b.rstrip("%")))
    return out.sort_values("sort").drop(columns="sort")


def funnel(orders: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame(columns=["stage", "count"])
    return pd.DataFrame({
        "stage": ["Placed", "Decided", "Approved"],
        "count": [len(orders), int((orders["status"] != "PENDING").sum()), int((orders["status"] == "APPROVED").sum())],
    })


def approval_hours(orders: pd.DataFrame) -> pd.Series:
    if orders.empty:
        return pd.Series(dtype=float)
    decided = orders.dropna(subset=["decided_at"])
    return (decided["decided_at"] - decided["created_at"]).dt.total_seconds() / 3600
