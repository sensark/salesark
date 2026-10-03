"""Quotation win probability: chance an open quotation is accepted or converted to an order."""

from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from erp.ml.features import LOST_QUOTE_STATUSES, OPEN_QUOTE_STATUSES
from erp.ml.registry import ModelResult

FEATURES = ["log_total", "discount_pct", "n_items", "valid_days", "cust_prior_orders",
            "cust_win_rate", "cust_prior_quotes", "sp_win_rate"]
MIN_SAMPLES = 25


def outcomes(quotes: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Adds `won` (1/0/NaN) and `resolved_at` for each quotation."""
    q = quotes.copy()
    now = pd.Timestamp(now)
    won = (q["status"] == "ACCEPTED") | q["converted_order_id"].notna()
    lapsed = q["status"].isin(OPEN_QUOTE_STATUSES) & q["valid_until"].notna() & (q["valid_until"] < now)
    lost = q["status"].isin(LOST_QUOTE_STATUSES) | lapsed
    q["won"] = np.where(won, 1.0, np.where(lost, 0.0, np.nan))
    q["resolved_at"] = q["accepted_at"].where(won, q["decided_at"].fillna(q["valid_until"]))
    q.loc[lapsed, "resolved_at"] = q.loc[lapsed, "valid_until"]
    q["resolved_at"] = q["resolved_at"].fillna(q["created_at"])
    return q


def quote_features(q: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    rows = []
    resolved = q[q["won"].notna()]
    for _, r in q.iterrows():
        known = resolved[resolved["resolved_at"] < r["created_at"]]
        cust = known[known["customer_id"] == r["customer_id"]]
        sp = known[known["sales_person_id"] == r["sales_person_id"]]
        valid_days = (r["valid_until"] - r["created_at"]).days if pd.notna(r["valid_until"]) else 30
        rows.append({
            "quotation_id": r["quotation_id"],
            "log_total": np.log1p(r["total"]),
            "discount_pct": r["discount_total"] / r["subtotal"] * 100 if r["subtotal"] else 0.0,
            "n_items": float(r["n_items"]),
            "valid_days": float(valid_days),
            "cust_prior_orders": float(np.log1p(((orders["customer_id"] == r["customer_id"])
                                                 & (orders["created_at"] < r["created_at"])).sum())),
            "cust_win_rate": float(cust["won"].mean()) if len(cust) else 0.5,
            "cust_prior_quotes": float(len(cust)),
            "sp_win_rate": float(sp["won"].mean()) if len(sp) else 0.5,
        })
    return pd.DataFrame(rows).set_index("quotation_id") if rows else pd.DataFrame(columns=FEATURES)


def heuristic_probability(feats: pd.DataFrame, base_rate: float) -> np.ndarray:
    loyalty = np.minimum(feats["cust_prior_orders"] / np.log1p(60), 1)
    p = 0.5 * base_rate + 0.25 * feats["cust_win_rate"] + 0.15 * loyalty + feats["discount_pct"] / 100
    return np.clip(p.to_numpy(), 0.02, 0.98)


def _model():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, C=0.5))


def train(quotes: pd.DataFrame, orders: pd.DataFrame, now: datetime) -> ModelResult:
    if quotes.empty:
        return ModelResult("quote_win", "none", 0, pd.DataFrame(columns=["win_probability"]))
    q = outcomes(quotes, now)
    feats = quote_features(q, orders)
    labelled = q[q["won"].notna()].sort_values("created_at")
    y = labelled.set_index("quotation_id")["won"].astype(int)
    base_rate = float(y.mean()) if len(y) else 0.4
    metrics: dict = {"base_rate": base_rate, "labelled": len(y)}
    model = None
    if len(y) >= MIN_SAMPLES and y.nunique() == 2:
        split = int(len(y) * 0.75)
        fit_ids, test_ids = y.index[:split], y.index[split:]
        if y[fit_ids].nunique() == 2 and y[test_ids].nunique() == 2:
            probe = _model().fit(feats.loc[fit_ids, FEATURES], y[fit_ids])
            metrics["auc"] = float(roc_auc_score(y[test_ids], probe.predict_proba(feats.loc[test_ids, FEATURES])[:, 1]))
            metrics["test_rows"] = len(test_ids)
        model = _model().fit(feats.loc[y.index, FEATURES], y)
        metrics["coefficients"] = dict(zip(FEATURES, map(float, model[-1].coef_[0])))

    open_ids = q.loc[q["won"].isna() & q["status"].isin(OPEN_QUOTE_STATUSES), "quotation_id"]
    open_x = feats.loc[open_ids, FEATURES] if len(open_ids) else feats.iloc[0:0]
    if open_x.empty:
        scores = pd.DataFrame(columns=["win_probability"])
    else:
        prob = model.predict_proba(open_x)[:, 1] if model else heuristic_probability(open_x, base_rate)
        scores = pd.DataFrame({"win_probability": prob}, index=open_x.index)
    return ModelResult(
        name="quote_win", method="logistic_regression" if model else "heuristic",
        n_samples=len(y), scores=scores, metrics=metrics, artifact=model,
    )
