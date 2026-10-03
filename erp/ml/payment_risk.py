"""Late-payment risk: probability an invoice is settled more than the grace period after due."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from erp.ml.features import PAYMENT_GRACE_DAYS
from erp.ml.registry import ModelResult

FEATURES = ["log_total", "credit_period_days", "credit_util", "prior_count", "prior_late_rate",
            "prior_avg_days_late"]
MIN_SAMPLES = 30


def risk_band(p: float) -> str:
    return "HIGH" if p >= 0.6 else "MEDIUM" if p >= 0.3 else "LOW"


def invoice_features(invoices: pd.DataFrame) -> pd.DataFrame:
    """Per-invoice features using only the customer's invoices whose outcome was known at issue time."""
    if invoices.empty:
        return pd.DataFrame(columns=FEATURES)
    inv = invoices.copy()
    deadline = inv["due_date"] + timedelta(days=PAYMENT_GRACE_DAYS)
    inv["deadline"] = deadline
    inv["late_flag"] = ~(inv["paid_at"].notna() & (inv["paid_at"] <= deadline))
    inv["days_late"] = (inv["paid_at"].fillna(deadline) - inv["due_date"]).dt.days.clip(lower=0)
    rows = []
    for _, r in inv.iterrows():
        prior = inv[(inv["customer_id"] == r["customer_id"]) & (inv["deadline"] < r["invoice_date"])]
        rows.append({
            "invoice_id": r["invoice_id"],
            "log_total": np.log1p(r["total"]),
            "credit_period_days": float(r["credit_period_days"] or 0),
            "credit_util": r["total"] / r["credit_limit"] if r["credit_limit"] else 0.0,
            "prior_count": float(len(prior)),
            "prior_late_rate": float(prior["late_flag"].mean()) if len(prior) else 0.0,
            "prior_avg_days_late": float(prior["days_late"].mean()) if len(prior) else 0.0,
        })
    return pd.DataFrame(rows).set_index("invoice_id")


def labels(invoices: pd.DataFrame, now: datetime) -> pd.Series:
    """1 = late, 0 = on time, only for invoices whose grace deadline has passed."""
    deadline = invoices["due_date"] + timedelta(days=PAYMENT_GRACE_DAYS)
    resolved = invoices[deadline < pd.Timestamp(now)]
    on_time = resolved["paid_at"].notna() & (resolved["paid_at"] <= deadline[resolved.index])
    return pd.Series((~on_time).astype(int).to_numpy(), index=resolved["invoice_id"])


def heuristic_probability(feats: pd.DataFrame, base_rate: float) -> np.ndarray:
    known = feats["prior_count"] > 0
    return np.where(known, 0.15 + 0.7 * feats["prior_late_rate"], base_rate).clip(0.02, 0.98)


def _model():
    return make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=500))


def train(invoices: pd.DataFrame, now: datetime) -> ModelResult:
    feats = invoice_features(invoices)
    y = labels(invoices, now) if not invoices.empty else pd.Series(dtype=int)
    train_x = feats.loc[y.index] if len(y) else feats.iloc[0:0]
    base_rate = float(y.mean()) if len(y) else 0.25
    metrics: dict = {"base_rate": base_rate, "labelled": len(y)}
    model = None
    if len(y) >= MIN_SAMPLES and y.nunique() == 2:
        order = invoices.set_index("invoice_id").loc[y.index, "invoice_date"].sort_values().index
        split = int(len(order) * 0.75)
        fit_ids, test_ids = order[:split], order[split:]
        if y[fit_ids].nunique() == 2 and y[test_ids].nunique() == 2:
            probe = _model().fit(train_x.loc[fit_ids], y[fit_ids])
            metrics["auc"] = float(roc_auc_score(y[test_ids], probe.predict_proba(train_x.loc[test_ids])[:, 1]))
            metrics["test_rows"] = len(test_ids)
        model = _model().fit(train_x, y)

    open_ids = invoices.loc[(invoices["balance_due"] > 0.005)
                            & invoices["status"].isin(["ISSUED", "PARTIALLY_PAID"]), "invoice_id"]
    open_x = feats.loc[open_ids] if len(open_ids) else feats.iloc[0:0]
    if open_x.empty:
        scores = pd.DataFrame(columns=["late_probability", "risk_band"])
    else:
        prob = model.predict_proba(open_x[FEATURES])[:, 1] if model else heuristic_probability(open_x, base_rate)
        scores = pd.DataFrame({"late_probability": prob, "risk_band": [risk_band(p) for p in prob]},
                              index=open_x.index)
    return ModelResult(
        name="payment_risk", method="logistic_regression" if model else "heuristic",
        n_samples=len(y), scores=scores, metrics=metrics, artifact=model,
    )
