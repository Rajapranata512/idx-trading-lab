"""Probability calibration for model_v2 predictions.

Wraps a base classifier with an isotonic-regression calibrator so that
``predict_proba()`` returns well-calibrated probabilities aligned with
observed win-rates.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


class CalibratedModelWrapper:
    """Wrapper that stores a base pipeline + a post-hoc calibrator.

    The calibrator is trained on a held-out validation fold to avoid
    overfitting.  ``predict_proba()`` returns calibrated probabilities.
    """

    def __init__(
        self,
        base_pipeline: Pipeline,
        calibrator: CalibratedClassifierCV | None = None,
    ):
        self.base_pipeline = base_pipeline
        self.calibrator = calibrator

    def predict_proba(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        if self.calibrator is not None:
            try:
                return self.calibrator.predict_proba(X)
            except Exception:
                pass
        return self.base_pipeline.predict_proba(X)

    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        if self.calibrator is not None:
            try:
                return self.calibrator.predict(X)
            except Exception:
                pass
        return self.base_pipeline.predict(X)


def calibrate_model(
    base_pipeline: Pipeline,
    X_cal: pd.DataFrame | np.ndarray,
    y_cal: np.ndarray,
    method: str = "isotonic",
) -> CalibratedModelWrapper:
    """Fit a post-hoc calibrator on held-out data.

    Parameters
    ----------
    base_pipeline : Pipeline
        Already-fitted base model.
    X_cal : array-like
        Feature matrix for calibration (must NOT overlap with training data).
    y_cal : array-like
        Labels for calibration.
    method : str
        ``"isotonic"`` or ``"sigmoid"`` (Platt scaling).

    Returns
    -------
    CalibratedModelWrapper with calibrator attached.
    """
    if len(y_cal) < 20 or len(np.unique(y_cal)) < 2:
        # Not enough data for calibration — return uncalibrated
        return CalibratedModelWrapper(base_pipeline, calibrator=None)

    try:
        cal = CalibratedClassifierCV(
            estimator=base_pipeline,
            method=method,
            cv="prefit",  # base model already fitted
        )
        cal.fit(X_cal, y_cal)
        return CalibratedModelWrapper(base_pipeline, calibrator=cal)
    except Exception:
        return CalibratedModelWrapper(base_pipeline, calibrator=None)


def evaluate_calibration(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Compute calibration diagnostics.

    Returns
    -------
    dict with:
        ece : Expected Calibration Error
        bin_stats : list of per-bin {mean_pred, mean_true, count}
    """
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    bin_stats: list[dict[str, float]] = []

    for i in range(n_bins):
        mask = (y_prob >= bins[i]) & (y_prob < bins[i + 1])
        if i == n_bins - 1:
            mask = (y_prob >= bins[i]) & (y_prob <= bins[i + 1])
        count = int(mask.sum())
        if count == 0:
            bin_stats.append({"mean_pred": 0.0, "mean_true": 0.0, "count": 0})
            continue
        mean_pred = float(y_prob[mask].mean())
        mean_true = float(y_true[mask].mean())
        ece += abs(mean_pred - mean_true) * (count / len(y_true))
        bin_stats.append({
            "mean_pred": round(mean_pred, 4),
            "mean_true": round(mean_true, 4),
            "count": count,
        })

    return {
        "ece": round(float(ece), 6),
        "n_bins": n_bins,
        "bin_stats": bin_stats,
    }
