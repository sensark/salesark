"""Customer lifetime value: expected approved revenue over the next 90 days."""

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from erp.ml.features import CUSTOMER_FEATURES, HORIZON_DAYS, backtest_split
from erp.ml.registry import ModelResult

MIN_SAMPLES = 60


def _model() -> GradientBoostingRegressor:
    return GradientBoostingRegressor(
        n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, loss="huber", random_state=0,
    )


def run_rate(feats: pd.DataFrame) -> np.ndarray:
    lifetime = feats["monetary"] / feats["tenure_days"].clip(lower=HORIZON_DAYS) * HORIZON_DAYS
    return (0.5 * feats["revenue_90d"] + 0.5 * lifetime).to_numpy()


def train(training: pd.DataFrame, current: pd.DataFrame) -> ModelResult:
    usable = len(training) >= MIN_SAMPLES and training["cutoff"].nunique() >= 4
    metrics: dict = {}
    model = None
    if usable:
        fit, test = backtest_split(training)
        if len(fit) >= MIN_SAMPLES // 2 and len(test):
            probe = _model().fit(fit[CUSTOMER_FEATURES], fit["future_revenue"])
            pred = probe.predict(test[CUSTOMER_FEATURES]).clip(min=0)
            metrics.update(
                mae=float(mean_absolute_error(test["future_revenue"], pred)),
                baseline_mae=float(mean_absolute_error(test["future_revenue"], run_rate(test))),
                test_rows=len(test),
            )
        model = _model().fit(training[CUSTOMER_FEATURES], training["future_revenue"])

    if current.empty:
        scores = pd.DataFrame(columns=["clv_90d"])
    else:
        pred = model.predict(current[CUSTOMER_FEATURES]) if model else run_rate(current)
        scores = pd.DataFrame({"clv_90d": np.clip(pred, 0, None)}, index=current.index)
    return ModelResult(
        name="clv", method="gradient_boosting" if model else "run_rate",
        n_samples=len(training), scores=scores, metrics=metrics, artifact=model,
    )
