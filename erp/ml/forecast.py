"""Weekly product demand forecasts and reorder recommendations."""

import json
import math
from datetime import datetime

import numpy as np
import pandas as pd

from erp import config
from erp.ml.features import weekly_demand
from erp.ml.registry import ModelResult

HISTORY_WEEKS = 52
HORIZON_WEEKS = 8
BACKTEST_WEEKS = 8
REVIEW_WEEKS = 4


def _fit_predict(series: pd.Series, steps: int) -> tuple[np.ndarray, float]:
    """Return Prophet's forecast and residual standard deviation."""
    values = series.to_numpy(dtype=float)
    from prophet import Prophet

    history = pd.DataFrame({"ds": series.index, "y": values})
    model = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        seasonality_mode="additive",
        uncertainty_samples=0,
    )
    model.fit(history)
    future = model.make_future_dataframe(
        periods=steps, freq="7D", include_history=False
    )
    forecast = np.clip(model.predict(future)["yhat"].to_numpy(), 0, None)
    fitted = model.predict(history[["ds"]])["yhat"].to_numpy()
    residuals = values - fitted
    return forecast, float(np.std(residuals[-26:]))


def reorder_plan(weekly: float, std: float, stock: int, lead_days: int, z: float) -> tuple[int, int, float | None]:
    """Returns (reorder point, suggested order qty, days of cover)."""
    lead_weeks = lead_days / 7
    safety = z * std * math.sqrt(lead_weeks)
    reorder_point = math.ceil(weekly * lead_weeks + safety)
    target = reorder_point + math.ceil(weekly * REVIEW_WEEKS)
    suggested = max(0, target - stock) if stock <= reorder_point else 0
    cover = stock / (weekly / 7) if weekly > 0 else None
    return reorder_point, suggested, cover


def train(items: pd.DataFrame, products: pd.DataFrame, now: datetime) -> ModelResult:
    """`products` needs columns product_id, stock."""
    if products.empty:
        return ModelResult("forecast", "none", 0, pd.DataFrame())
    ids = products["product_id"].tolist()
    demand = weekly_demand(items, ids, now, HISTORY_WEEKS)

    abs_err = actual_total = 0.0
    for pid in ids:
        series = demand[pid]
        train_part, test_part = series.iloc[:-BACKTEST_WEEKS], series.iloc[-BACKTEST_WEEKS:]
        actual = test_part.to_numpy()
        prophet_forecast, _ = _fit_predict(train_part, BACKTEST_WEEKS)
        abs_err += float(np.abs(prophet_forecast - actual).sum())
        actual_total += float(actual.sum())

    rows, methods = [], []
    stock = products.set_index("product_id")["stock"]
    for pid in ids:
        forecast, std = _fit_predict(demand[pid], HORIZON_WEEKS)
        method = "prophet"
        weekly = float(forecast[:4].mean())
        rop, qty, cover = reorder_plan(weekly, std, int(stock[pid]), config.REPLENISHMENT_LEAD_DAYS,
                                       config.SERVICE_LEVEL_Z)
        methods.append(method)
        rows.append({
            "product_id": pid, "method": method, "weekly_demand": weekly, "demand_std": std,
            "forecast_30d": weekly * 30 / 7, "reorder_point": rop, "suggested_qty": qty,
            "days_of_cover": cover,
            "forecast_json": json.dumps({
                "history": demand[pid].tail(26).round(2).tolist(),
                "history_start": demand.index[-26].strftime("%Y-%m-%d"),
                "forecast": [round(float(v), 2) for v in forecast],
            }),
        })
    metrics = {
        "wape": abs_err / actual_total if actual_total else None,
        "methods": pd.Series(methods).value_counts().to_dict(),
        "lead_days": config.REPLENISHMENT_LEAD_DAYS, "service_z": config.SERVICE_LEVEL_Z,
    }
    return ModelResult(
        name="forecast",
        method="prophet",
        n_samples=len(ids),
        scores=pd.DataFrame(rows).set_index("product_id"), metrics=metrics,
    )
