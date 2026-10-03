"""RFM customer segmentation with KMeans; clusters are named by their RFM rank."""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from erp.ml.registry import ModelResult

SEGMENTS = ("Champions", "Loyal", "At risk", "Dormant")


def _rfm(current: pd.DataFrame) -> np.ndarray:
    return np.column_stack([
        current["recency_days"], np.log1p(current["frequency"]), np.log1p(current["monetary"]),
    ])


def _rule_segments(current: pd.DataFrame) -> list[str]:
    score = (-current["recency_days"].rank(pct=True) + current["frequency"].rank(pct=True)
             + current["monetary"].rank(pct=True))
    pct = score.rank(pct=True)
    return [SEGMENTS[min(len(SEGMENTS) - 1, int((1 - p) * len(SEGMENTS)))] for p in pct]


def train(current: pd.DataFrame) -> ModelResult:
    if current.empty:
        return ModelResult("segmentation", "none", 0, pd.DataFrame(columns=["segment"]))
    if len(current) < 8:
        return ModelResult("segmentation", "rfm_rules", len(current),
                           pd.DataFrame({"segment": _rule_segments(current)}, index=current.index))

    scaler = StandardScaler()
    x = scaler.fit_transform(_rfm(current))
    km = KMeans(n_clusters=len(SEGMENTS), n_init=10, random_state=0).fit(x)
    # Higher is better: recent, frequent, high spend.
    quality = -km.cluster_centers_[:, 0] + km.cluster_centers_[:, 1] + km.cluster_centers_[:, 2]
    names = {cluster: SEGMENTS[rank] for rank, cluster in enumerate(np.argsort(-quality))}
    labels = [names[c] for c in km.labels_]
    return ModelResult(
        name="segmentation", method="kmeans_rfm", n_samples=len(current),
        scores=pd.DataFrame({"segment": labels}, index=current.index),
        metrics={"silhouette": float(silhouette_score(x, km.labels_)),
                 "sizes": pd.Series(labels).value_counts().to_dict()},
        artifact={"scaler": scaler, "kmeans": km, "names": names},
    )
