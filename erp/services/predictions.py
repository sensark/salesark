"""Train predictive models, persist scores and expose prescriptive recommendations."""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from erp.ml import churn, clv, forecast, payment_risk, quote_win, segmentation
from erp.ml.features import (
    customer_features,
    customer_training_set,
    load_invoices,
    load_items,
    load_orders,
    load_quotations,
    load_returns,
)
from erp.ml.registry import ModelResult, latest_runs, record_run, save_artifact
from erp.models import (
    Customer,
    CustomerScore,
    InvoiceRiskScore,
    MLModelRun,
    Product,
    ProductForecast,
    Quotation,
    QuotationScore,
    SalesInvoice,
    User,
)
from erp.permissions import require_action
from erp.services import audit, notifications

HIGH_CHURN = 0.6
MEDIUM_CHURN = 0.35


def recommended_action(churn_p: float, segment: str | None, high_value: bool) -> str:
    if churn_p >= HIGH_CHURN and high_value:
        return "Priority: account owner call this week and offer loyalty pricing"
    if churn_p >= HIGH_CHURN:
        return "Win-back email with a volume-tier offer"
    if churn_p >= MEDIUM_CHURN:
        return "Check-in call; share new products and open quotations"
    if segment == "Champions":
        return "Upsell: propose the next discount tier or a bundle"
    return "Maintain regular contact cadence"


def _primary_sales_person(orders: pd.DataFrame) -> pd.Series:
    if orders.empty:
        return pd.Series(dtype=int)
    return orders.groupby("customer_id")["sales_person_id"].agg(lambda s: s.value_counts().index[0])


def _persist_customers(session: Session, current: pd.DataFrame, orders: pd.DataFrame,
                       churn_r: ModelResult, clv_r: ModelResult, seg_r: ModelResult, now: datetime) -> int:
    session.execute(delete(CustomerScore))
    if current.empty:
        return 0
    owners = _primary_sales_person(orders)
    run_rate = pd.Series(clv.run_rate(current), index=current.index)
    value_cut = current["monetary"].quantile(0.75)
    high_risk = 0
    for cid, row in current.iterrows():
        p = float(churn_r.scores.at[cid, "churn_probability"])
        value = float(clv_r.scores.at[cid, "clv_90d"])
        segment = seg_r.scores.at[cid, "segment"]
        high_risk += p >= HIGH_CHURN
        session.add(CustomerScore(
            customer_id=int(cid), sales_person_id=int(owners[cid]) if cid in owners.index else None,
            churn_probability=p, churn_drivers=json.dumps(churn_r.scores.at[cid, "drivers"]),
            clv_90d=value, value_at_risk=p * max(value, float(run_rate[cid])), segment=segment,
            recency_days=int(row["recency_days"]), frequency=int(row["frequency"]),
            monetary=float(row["monetary"]),
            recommended_action=recommended_action(p, segment, row["monetary"] >= value_cut),
            scored_at=now,
        ))
    return int(high_risk)


def _plain(value):
    if isinstance(value, float) and np.isnan(value):
        return None
    return value.item() if isinstance(value, np.generic) else value


def _persist_simple(session: Session, model, key: str, scores: pd.DataFrame, now: datetime) -> None:
    session.execute(delete(model))
    for ident, row in scores.iterrows():
        values = {k: _plain(v) for k, v in row.to_dict().items()}
        session.add(model(**{key: int(ident)}, **values, scored_at=now))


def train_forecast_only(
    session: Session, actor_id: int, now: datetime | None = None,
) -> ModelResult:
    actor = session.get(User, actor_id)
    if actor is None:
        raise PermissionError("User not found.")
    require_action(actor.role, "analytics.retrain")
    now = now or datetime.now()
    items = load_items(session)
    products = pd.DataFrame(session.execute(
        select(Product.id.label("product_id"), Product.stock)
        .where(Product.active.is_(True))
    ).mappings().all())
    result = forecast.train(items, products, now)
    _persist_simple(session, ProductForecast, "product_id", result.scores, now)
    record_run(
        session, model_name=result.name, method=result.method,
        n_samples=result.n_samples, metrics=result.metrics,
        artifact_path=None, actor_id=actor.id,
    )
    audit.record(
        session, actor_id=actor.id, action="RETRAIN_FORECAST",
        entity_type="ML_MODELS", entity_id=0,
        changes={"method": result.method, "metrics": result.metrics},
    )
    session.flush()
    return result


def train_all(
    session: Session, actor_id: int, now: datetime | None = None, model_dir: Path | None = None,
) -> dict[str, ModelResult]:
    actor = session.get(User, actor_id)
    if actor is None:
        raise PermissionError("User not found.")
    require_action(actor.role, "analytics.retrain")
    now = now or datetime.now()

    orders, items = load_orders(session), load_items(session)
    returns, invoices = load_returns(session), load_invoices(session)
    quotes = load_quotations(session)
    products = pd.DataFrame(session.execute(select(Product.id.label("product_id"), Product.stock)
                                            .where(Product.active.is_(True))).mappings().all())

    current = customer_features(orders, returns, invoices, now)
    training = customer_training_set(orders, returns, invoices, now)
    results = {
        "churn": churn.train(training, current),
        "clv": clv.train(training, current),
        "segmentation": segmentation.train(current),
        "payment_risk": payment_risk.train(invoices, now),
        "quote_win": quote_win.train(quotes, orders, now),
        "forecast": forecast.train(items, products, now),
    }

    high_risk = _persist_customers(session, current, orders, results["churn"], results["clv"],
                                   results["segmentation"], now)
    _persist_simple(session, InvoiceRiskScore, "invoice_id", results["payment_risk"].scores, now)
    _persist_simple(session, QuotationScore, "quotation_id", results["quote_win"].scores, now)
    _persist_simple(session, ProductForecast, "product_id", results["forecast"].scores, now)

    for result in results.values():
        path = save_artifact(result.name, result.artifact, model_dir) if result.artifact is not None else None
        record_run(session, model_name=result.name, method=result.method, n_samples=result.n_samples,
                   metrics=result.metrics, artifact_path=path, actor_id=actor.id)
    session.flush()

    reorder = int((results["forecast"].scores.get("suggested_qty", pd.Series(dtype=int)) > 0).sum())
    summary = {name: {"method": r.method, "samples": r.n_samples,
                      **{k: v for k, v in r.metrics.items() if isinstance(v, (int, float))}}
               for name, r in results.items()}
    audit.record(session, actor_id=actor.id, action="RETRAIN", entity_type="ML_MODELS",
                 entity_id=0, changes=summary)
    notifications.notify_admins(
        session, f"Predictive models retrained by {actor.name}: {high_risk} customers at high churn risk, "
                 f"{reorder} products need reordering.",
    )
    return results


def customer_scores_frame(session: Session, sales_person_id: int | None = None) -> pd.DataFrame:
    stmt = (
        select(CustomerScore, Customer.name.label("customer"), Customer.company, Customer.region,
               Customer.phone, Customer.email, User.name.label("sales_person"))
        .join(Customer, Customer.id == CustomerScore.customer_id)
        .outerjoin(User, User.id == CustomerScore.sales_person_id)
    )
    if sales_person_id is not None:
        stmt = stmt.where(CustomerScore.sales_person_id == sales_person_id)
    rows = []
    for score, customer, company, region, phone, email, sales_person in session.execute(stmt):
        rows.append({
            "customer_id": score.customer_id, "customer": customer, "company": company or "",
            "region": region, "phone": phone or "", "email": email, "sales_person": sales_person or "",
            "churn_probability": score.churn_probability, "clv_90d": score.clv_90d,
            "value_at_risk": score.value_at_risk, "segment": score.segment,
            "recency_days": score.recency_days, "frequency": score.frequency, "monetary": score.monetary,
            "drivers": "; ".join(json.loads(score.churn_drivers or "[]")),
            "action": score.recommended_action, "scored_at": score.scored_at,
        })
    return pd.DataFrame(rows)


def retention_actions(session: Session, sales_person_id: int | None = None, limit: int = 25) -> pd.DataFrame:
    """Customers ranked by expected revenue at risk, highest first."""
    df = customer_scores_frame(session, sales_person_id)
    if df.empty:
        return df
    df = df[df["churn_probability"] >= MEDIUM_CHURN]
    return df.sort_values("value_at_risk", ascending=False).head(limit)


def reorder_frame(session: Session) -> pd.DataFrame:
    rows = session.execute(
        select(Product, ProductForecast).join(ProductForecast, ProductForecast.product_id == Product.id)
        .order_by(Product.category, Product.name)
    )
    return pd.DataFrame([{
        "product_id": p.id, "sku": p.sku, "product": p.name, "category": p.category, "stock": p.stock,
        "reorder_level": p.reorder_level, "weekly_demand": f.weekly_demand, "forecast_30d": f.forecast_30d,
        "reorder_point": f.reorder_point, "suggested_qty": f.suggested_qty, "days_of_cover": f.days_of_cover,
        "method": f.method, "series": json.loads(f.forecast_json or "{}"), "scored_at": f.scored_at,
    } for p, f in rows])


def invoice_risk_map(session: Session) -> dict[int, tuple[float, str]]:
    return {s.invoice_id: (s.late_probability, s.risk_band) for s in session.scalars(select(InvoiceRiskScore))}


def invoice_risk_frame(session: Session) -> pd.DataFrame:
    rows = session.execute(
        select(InvoiceRiskScore, SalesInvoice, Customer.name)
        .join(SalesInvoice, SalesInvoice.id == InvoiceRiskScore.invoice_id)
        .join(Customer, Customer.id == SalesInvoice.customer_id)
        .where(SalesInvoice.balance_due > 0)
    )
    return pd.DataFrame([{
        "invoice": inv.invoice_no, "customer": name, "due_date": inv.due_date,
        "outstanding": float(inv.balance_due), "late_probability": s.late_probability,
        "risk_band": s.risk_band, "expected_late_amount": s.late_probability * float(inv.balance_due),
    } for s, inv, name in rows])


def quote_scores_frame(session: Session) -> pd.DataFrame:
    rows = session.execute(
        select(QuotationScore, Quotation, Customer.name, User.name)
        .join(Quotation, Quotation.id == QuotationScore.quotation_id)
        .join(Customer, Customer.id == Quotation.customer_id)
        .join(User, User.id == Quotation.sales_person_id)
    )
    return pd.DataFrame([{
        "quotation": q.quotation_no, "customer": cname, "sales_person": sp, "status": q.status,
        "total": float(q.total), "valid_until": q.valid_until, "win_probability": s.win_probability,
        "expected_value": s.win_probability * float(q.total),
    } for s, q, cname, sp in rows])


def model_health(session: Session) -> list[dict]:
    names = {u.id: u.name for u in session.scalars(select(User))}
    return [{
        "model": run.model_name, "method": run.method, "samples": run.n_samples,
        "trained_at": run.trained_at, "trained_by": names.get(run.trained_by_id, ""),
        "metrics": json.loads(run.metrics_json or "{}"),
    } for run in latest_runs(session).values()]


def last_trained_at(session: Session) -> datetime | None:
    return session.scalar(select(MLModelRun.trained_at).order_by(MLModelRun.trained_at.desc()).limit(1))
