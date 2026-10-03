import json
import random
from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from erp.ml import churn, forecast, payment_risk, quote_win, segmentation
from erp.ml.features import customer_features, customer_training_set
from erp.models import (
    STATUS_APPROVED,
    Customer,
    CustomerScore,
    MLModelRun,
    Order,
    OrderItem,
    ProductForecast,
)
from erp.services import predictions

NOW = datetime(2026, 6, 1, 12, 0)


def _orders(rows):
    return pd.DataFrame([
        {"order_id": i, "customer_id": c, "sales_person_id": 1, "created_at": pd.Timestamp(d),
         "subtotal": t, "discount_total": 0.0, "total": t}
        for i, (c, d, t) in enumerate(rows)
    ])


EMPTY_RETURNS = pd.DataFrame(columns=["customer_id", "created_at"])
EMPTY_INVOICES = pd.DataFrame(columns=["invoice_id", "customer_id", "due_date", "paid_at"])


def test_customer_features_ignore_rows_after_cutoff():
    base = [(1, NOW - timedelta(days=d), 100.0) for d in (200, 150, 100, 40)]
    later = base + [(1, NOW + timedelta(days=5), 9999.0), (2, NOW + timedelta(days=1), 50.0)]
    a = customer_features(_orders(base), EMPTY_RETURNS, EMPTY_INVOICES, NOW)
    b = customer_features(_orders(later), EMPTY_RETURNS, EMPTY_INVOICES, NOW)
    pd.testing.assert_frame_equal(a, b)
    assert list(a.index) == [1]
    assert a.at[1, "recency_days"] == 40
    assert a.at[1, "frequency"] == 4


def test_training_labels_mark_customers_without_future_orders_as_churned():
    rows = []
    for d in range(0, 400, 20):
        rows.append((1, NOW - timedelta(days=400 - d), 100.0))
    for d in range(0, 200, 20):
        rows.append((2, NOW - timedelta(days=400 - d), 100.0))
    train = customer_training_set(_orders(rows), EMPTY_RETURNS, EMPTY_INVOICES, NOW)
    last = train[train["cutoff"] == train["cutoff"].max()]
    assert last.loc[1, "churned"] == 0
    assert last.loc[2, "churned"] == 1


def test_churn_falls_back_to_heuristic_with_one_class():
    rows = [(1, NOW - timedelta(days=d), 100.0) for d in range(10, 400, 15)]
    orders = _orders(rows)
    train = customer_training_set(orders, EMPTY_RETURNS, EMPTY_INVOICES, NOW)
    current = customer_features(orders, EMPTY_RETURNS, EMPTY_INVOICES, NOW)
    result = churn.train(train, current)
    assert result.method == "heuristic"
    assert 0 <= result.scores.at[1, "churn_probability"] <= 1


def test_churn_heuristic_ranks_lapsed_customer_higher():
    rows = [(1, NOW - timedelta(days=d), 100.0) for d in range(5, 300, 10)]
    rows += [(2, NOW - timedelta(days=d), 100.0) for d in range(150, 300, 10)]
    current = customer_features(_orders(rows), EMPTY_RETURNS, EMPTY_INVOICES, NOW)
    p = churn.heuristic_probability(current)
    assert p[list(current.index).index(2)] > p[list(current.index).index(1)]
    assert churn.drivers(current.loc[2])


def test_reorder_plan_formula():
    rop, qty, cover = forecast.reorder_plan(weekly=14.0, std=4.0, stock=10, lead_days=14, z=1.65)
    # 14/wk * 2wk + 1.65 * 4 * sqrt(2) = 28 + 9.33 -> 38; target = 38 + 56
    assert rop == 38
    assert qty == 38 + 56 - 10
    assert cover == pytest.approx(5.0)
    assert forecast.reorder_plan(14.0, 4.0, 500, 14, 1.65)[1] == 0


def test_forecast_uses_prophet_for_sparse_history():
    items = pd.DataFrame({"product_id": [7, 7], "qty": [5, 3],
                          "created_at": [pd.Timestamp(NOW - timedelta(days=10)), pd.Timestamp(NOW - timedelta(days=20))]})
    result = forecast.train(items, pd.DataFrame({"product_id": [7], "stock": [0]}), NOW)
    row = result.scores.loc[7]
    assert result.method == "prophet"
    assert row["method"] == "prophet"
    assert row["weekly_demand"] >= 0
    assert json.loads(row["forecast_json"])["forecast"]


def test_prophet_forecast_returns_nonnegative_weekly_predictions():
    pytest.importorskip("prophet")
    index = pd.date_range(NOW - timedelta(weeks=40), periods=40, freq="7D")
    series = pd.Series([2 + week * 0.2 for week in range(40)], index=index)

    predicted, residual_std = forecast._fit_predict(series, 8)

    assert len(predicted) == 8
    assert (predicted >= 0).all()
    assert residual_std >= 0


def _invoice(i, cust, issued, due, paid, total=1000.0):
    return {"invoice_id": i, "customer_id": cust, "status": "PAID" if paid else "ISSUED",
            "invoice_date": pd.Timestamp(issued), "due_date": pd.Timestamp(due), "total": total,
            "balance_due": 0.0 if paid else total, "credit_limit": 0.0, "credit_period_days": 30,
            "last_payment_at": pd.Timestamp(paid) if paid else pd.NaT,
            "paid_at": pd.Timestamp(paid) if paid else pd.NaT}


def test_payment_features_only_use_outcomes_known_at_issue():
    t0 = NOW - timedelta(days=200)
    invoices = pd.DataFrame([
        _invoice(1, 5, t0, t0 + timedelta(days=30), t0 + timedelta(days=80)),       # late
        _invoice(2, 5, t0 + timedelta(days=20), t0 + timedelta(days=50), None),     # outcome unknown at #2
        _invoice(3, 5, t0 + timedelta(days=120), t0 + timedelta(days=150), None),
    ])
    feats = payment_risk.invoice_features(invoices)
    assert feats.at[2, "prior_count"] == 0
    assert feats.at[3, "prior_count"] == 2
    assert feats.at[3, "prior_late_rate"] == 1.0
    labels = payment_risk.labels(invoices, NOW)
    assert labels[1] == 1 and labels[2] == 1


def test_quote_outcomes():
    q = pd.DataFrame([
        {"quotation_id": 1, "status": "ACCEPTED", "converted_order_id": None},
        {"quotation_id": 2, "status": "REJECTED", "converted_order_id": None},
        {"quotation_id": 3, "status": "SENT", "converted_order_id": None},
        {"quotation_id": 4, "status": "SENT", "converted_order_id": None},
    ])
    q["created_at"] = pd.Timestamp(NOW - timedelta(days=60))
    q["valid_until"] = [pd.Timestamp(NOW + timedelta(days=d)) for d in (0, 0, -5, 10)]
    q["decided_at"] = pd.NaT
    q["accepted_at"] = pd.NaT
    out = quote_win.outcomes(q, NOW).set_index("quotation_id")["won"]
    assert out[1] == 1 and out[2] == 0 and out[3] == 0
    assert pd.isna(out[4])


def test_segmentation_names_best_cluster_champions():
    rng = random.Random(1)
    rows = []
    for cid in range(1, 21):
        good = cid <= 5
        rows.append({"recency_days": rng.randint(1, 10) if good else rng.randint(100, 300),
                     "frequency": rng.randint(30, 40) if good else rng.randint(1, 5),
                     "monetary": rng.uniform(5e5, 6e5) if good else rng.uniform(1e3, 5e4)})
    current = pd.DataFrame(rows, index=range(1, 21))
    result = segmentation.train(current)
    assert set(result.scores.loc[1:5, "segment"]) == {"Champions"}


def _seed_orders(session, data, customer, days_ago):
    for n, d in enumerate(days_ago):
        created = NOW - timedelta(days=d)
        session.add(Order(
            order_no=f"SO-{customer.id}-{n}", customer_id=customer.id, sales_person_id=data["sales"].id,
            status=STATUS_APPROVED, subtotal=Decimal("100"), discount_total=Decimal("0"), total=Decimal("100"),
            created_at=created, decided_at=created,
            items=[OrderItem(product_id=data["pen"].id, qty=3, unit_price=Decimal("10"),
                             discount_pct=Decimal("0"), line_total=Decimal("30"))],
        ))


def test_train_all_persists_scores_and_requires_permission(session, data, tmp_path):
    lapsed = Customer(name="Lapsed", email="l@example.com", region="South")
    session.add(lapsed)
    session.flush()
    _seed_orders(session, data, data["customer"], range(3, 360, 12))
    _seed_orders(session, data, lapsed, range(160, 360, 12))
    session.flush()

    with pytest.raises(PermissionError):
        predictions.train_all(session, data["sales"].id, now=NOW, model_dir=tmp_path)

    predictions.train_all(session, data["admin"].id, now=NOW, model_dir=tmp_path)
    scores = {s.customer_id: s for s in session.query(CustomerScore)}
    assert scores[lapsed.id].churn_probability > scores[data["customer"].id].churn_probability
    assert scores[lapsed.id].sales_person_id == data["sales"].id
    assert json.loads(scores[lapsed.id].churn_drivers)
    assert session.query(ProductForecast).count() == 2
    assert {r.model_name for r in session.query(MLModelRun)} == {
        "churn", "clv", "segmentation", "payment_risk", "quote_win", "forecast"}

    actions = predictions.retention_actions(session, sales_person_id=data["sales"].id)
    assert actions.iloc[0]["customer_id"] == lapsed.id

    predictions.train_all(session, data["admin"].id, now=NOW, model_dir=tmp_path)
    assert session.query(CustomerScore).count() == 2


def test_train_forecast_only_persists_prophet_scores(session, data):
    with pytest.raises(PermissionError):
        predictions.train_forecast_only(session, data["sales"].id, now=NOW)

    result = predictions.train_forecast_only(session, data["admin"].id, now=NOW)

    assert result.method == "prophet"
    assert session.query(ProductForecast).count() == 2
    run = session.query(MLModelRun).filter_by(model_name="forecast").one()
    assert run.method == "prophet"
    assert session.query(CustomerScore).count() == 0
