import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from erp import config
from erp.models import MLModelRun


@dataclass
class ModelResult:
    name: str
    method: str
    n_samples: int
    scores: pd.DataFrame
    metrics: dict[str, Any] = field(default_factory=dict)
    artifact: Any = None


def save_artifact(name: str, obj: Any, model_dir: Path | None = None) -> str:
    directory = model_dir or config.MODEL_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.joblib"
    joblib.dump(obj, path)
    return str(path)


def record_run(
    session: Session,
    *,
    model_name: str,
    method: str,
    n_samples: int,
    metrics: dict[str, Any],
    artifact_path: str | None,
    actor_id: int | None,
) -> MLModelRun:
    run = MLModelRun(
        model_name=model_name, method=method, n_samples=n_samples,
        metrics_json=json.dumps(metrics, default=float), artifact_path=artifact_path,
        trained_by_id=actor_id,
    )
    session.add(run)
    return run


def latest_runs(session: Session) -> dict[str, MLModelRun]:
    runs = session.scalars(select(MLModelRun).order_by(MLModelRun.trained_at))
    return {run.model_name: run for run in runs}
