"""Customer churn: probability of no approved order in the next 90 days."""

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import brier_score_loss, roc_auc_score

from erp.ml.features import CUSTOMER_FEATURES, HORIZON_DAYS, backtest_split
from erp.ml.registry import ModelResult

MIN_SAMPLES = 60


def _model() -> GradientBoostingClassifier:
    return GradientBoostingClassifier(
        n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0,
    )


def heuristic_probability(feats: pd.DataFrame) -> np.ndarray:
    z = 1.4 * (feats["gap_ratio"].clip(upper=6) - 1.5) - 1.2 * feats["revenue_trend"] \
        + feats["recency_days"] / HORIZON_DAYS - 0.5
    return 1 / (1 + np.exp(-z.to_numpy()))


def drivers(row: pd.Series) -> list[str]:
    reasons = []
    if row["recency_days"] > max(30, 1.5 * row["avg_gap_days"]):
        reasons.append(f"No order for {row['recency_days']:.0f} days (usual gap {row['avg_gap_days']:.0f})")
    if row["revenue_trend"] < -0.25:
        reasons.append("Spend down sharply vs previous 90 days")
    if row["orders_90d"] == 0 and row["orders_prev_90d"] > 0:
        reasons.append("No orders this quarter")
    if row["avg_days_late"] > 10:
        reasons.append(f"Pays {row['avg_days_late']:.0f} days late on average")
    if row["return_count"] >= 2:
        reasons.append(f"{row['return_count']:.0f} returns raised")
    return reasons[:3]


def train(training: pd.DataFrame, current: pd.DataFrame) -> ModelResult:
    usable = len(training) >= MIN_SAMPLES and training["churned"].nunique() == 2 \
        and training["cutoff"].nunique() >= 4
    metrics: dict = {"base_rate": float(training["churned"].mean()) if len(training) else 0.0}
    model = None
    if usable:
        fit, test = backtest_split(training)
        if len(fit) >= MIN_SAMPLES // 2 and fit["churned"].nunique() == 2 and test["churned"].nunique() == 2:
            probe = _model().fit(fit[CUSTOMER_FEATURES], fit["churned"])
            p = probe.predict_proba(test[CUSTOMER_FEATURES])[:, 1]
            metrics.update(auc=float(roc_auc_score(test["churned"], p)),
                           brier=float(brier_score_loss(test["churned"], p)), test_rows=len(test))
        model = _model().fit(training[CUSTOMER_FEATURES], training["churned"])
        metrics["importance"] = dict(sorted(
            zip(CUSTOMER_FEATURES, map(float, model.feature_importances_)),
            key=lambda kv: -kv[1])[:6])

    if current.empty:
        scores = pd.DataFrame(columns=["churn_probability", "drivers"])
    else:
        prob = model.predict_proba(current[CUSTOMER_FEATURES])[:, 1] if model else heuristic_probability(current)
        scores = pd.DataFrame({
            "churn_probability": prob,
            "drivers": [drivers(row) for _, row in current.iterrows()],
        }, index=current.index)
    return ModelResult(
        name="churn", method="gradient_boosting" if model else "heuristic",
        n_samples=len(training), scores=scores, metrics=metrics, artifact=model,
    )
