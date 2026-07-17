"""Leakage-safe post-hoc probability calibration for model_v2."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.pipeline import Pipeline


class ProbabilityCalibrator:
    """Calibrate one-dimensional base probabilities."""

    def __init__(self, method: str):
        method_key = str(method).strip().lower()
        if method_key not in {"sigmoid", "isotonic"}:
            raise ValueError(f"Unsupported calibration method: {method}")
        self.method = method_key
        self.estimator: Any | None = None

    @staticmethod
    def _as_probability_column(values: np.ndarray) -> np.ndarray:
        return np.asarray(values, dtype=float).reshape(-1, 1)

    def fit(self, raw_probabilities: np.ndarray, y_true: np.ndarray) -> "ProbabilityCalibrator":
        raw = np.asarray(raw_probabilities, dtype=float).reshape(-1)
        labels = np.asarray(y_true, dtype=int).reshape(-1)
        if self.method == "sigmoid":
            estimator = LogisticRegression(solver="lbfgs", max_iter=500)
            estimator.fit(self._as_probability_column(raw), labels)
        else:
            estimator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            estimator.fit(raw, labels)
        self.estimator = estimator
        return self

    def predict(self, raw_probabilities: np.ndarray) -> np.ndarray:
        if self.estimator is None:
            raise RuntimeError("Probability calibrator is not fitted")
        raw = np.asarray(raw_probabilities, dtype=float).reshape(-1)
        if self.method == "sigmoid":
            calibrated = self.estimator.predict_proba(self._as_probability_column(raw))[:, 1]
        else:
            calibrated = self.estimator.predict(raw)
        return np.clip(np.asarray(calibrated, dtype=float), 0.001, 0.999)


class CalibratedModelWrapper:
    """Store a fitted base pipeline and a calibration-only post-processor."""

    def __init__(
        self,
        base_pipeline: Pipeline,
        calibrator: ProbabilityCalibrator | None = None,
        calibration_method: str = "",
        selection_diagnostics: dict[str, Any] | None = None,
    ):
        self.base_pipeline = base_pipeline
        self.calibrator = calibrator
        self.calibration_method = str(calibration_method)
        self.selection_diagnostics = selection_diagnostics or {}

    def predict_proba(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        base_probabilities = np.asarray(self.base_pipeline.predict_proba(X), dtype=float)
        if self.calibrator is None:
            return base_probabilities
        calibrated = self.calibrator.predict(base_probabilities[:, 1])
        return np.column_stack([1.0 - calibrated, calibrated])

    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


def _ece_value(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    labels = np.asarray(y_true, dtype=int).reshape(-1)
    probabilities = np.asarray(y_prob, dtype=float).reshape(-1)
    if len(labels) == 0:
        return 1.0
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for idx in range(n_bins):
        upper_inclusive = idx == n_bins - 1
        mask = (probabilities >= bins[idx]) & (
            probabilities <= bins[idx + 1] if upper_inclusive else probabilities < bins[idx + 1]
        )
        count = int(mask.sum())
        if count:
            ece += abs(float(probabilities[mask].mean()) - float(labels[mask].mean())) * (count / len(labels))
    return float(ece)


def _fit_probability_calibrator(
    method: str,
    raw_probabilities: np.ndarray,
    y_true: np.ndarray,
) -> ProbabilityCalibrator:
    return ProbabilityCalibrator(method).fit(raw_probabilities, y_true)


def calibrate_model(
    base_pipeline: Pipeline,
    X_cal: pd.DataFrame | np.ndarray,
    y_cal: np.ndarray,
    method: str = "auto",
) -> CalibratedModelWrapper:
    """Fit Platt or isotonic calibration on a dedicated chronological window.

    For ``method="auto"``, the last 25% of the calibration window selects the
    method by ECE and Brier score. The selected calibrator is then refitted on
    the full calibration window. The untouched test window must be evaluated by
    the caller.
    """
    if len(y_cal) < 20 or len(np.unique(y_cal)) < 2:
        return CalibratedModelWrapper(base_pipeline, calibrator=None)

    try:
        labels = np.asarray(y_cal, dtype=int).reshape(-1)
        raw = np.asarray(base_pipeline.predict_proba(X_cal), dtype=float)[:, 1]
        method_key = str(method).strip().lower()
        diagnostics: dict[str, Any] = {"requested_method": method_key, "candidates": {}}

        if method_key == "auto":
            split = max(20, int(len(labels) * 0.75))
            can_select = (
                split < len(labels)
                and len(np.unique(labels[:split])) >= 2
                and len(np.unique(labels[split:])) >= 2
            )
            selected_method = "sigmoid"
            if can_select:
                ranked: list[tuple[tuple[float, float], str]] = []
                for candidate_method in ["sigmoid", "isotonic"]:
                    candidate = _fit_probability_calibrator(
                        candidate_method,
                        raw[:split],
                        labels[:split],
                    )
                    candidate_prob = candidate.predict(raw[split:])
                    ece = _ece_value(labels[split:], candidate_prob)
                    brier = float(brier_score_loss(labels[split:], candidate_prob))
                    diagnostics["candidates"][candidate_method] = {
                        "selection_rows": int(len(labels) - split),
                        "ece": round(ece, 6),
                        "brier": round(brier, 6),
                    }
                    ranked.append(((ece, brier), candidate_method))
                ranked.sort(key=lambda row: row[0])
                selected_method = ranked[0][1]
            diagnostics["selection_strategy"] = (
                "temporal_calibration_holdout" if can_select else "sigmoid_small_or_single_class_holdout"
            )
        elif method_key in {"sigmoid", "isotonic"}:
            selected_method = method_key
            diagnostics["selection_strategy"] = "explicit"
        else:
            raise ValueError(f"Unsupported calibration method: {method}")

        calibrator = _fit_probability_calibrator(selected_method, raw, labels)
        diagnostics["selected_method"] = selected_method
        diagnostics["fit_rows"] = int(len(labels))
        return CalibratedModelWrapper(
            base_pipeline,
            calibrator=calibrator,
            calibration_method=selected_method,
            selection_diagnostics=diagnostics,
        )
    except Exception as exc:
        return CalibratedModelWrapper(
            base_pipeline,
            calibrator=None,
            selection_diagnostics={"error": f"{type(exc).__name__}:{exc}"},
        )


def evaluate_calibration(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Compute expected calibration error and per-bin diagnostics."""
    labels = np.asarray(y_true, dtype=int).reshape(-1)
    probabilities = np.asarray(y_prob, dtype=float).reshape(-1)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_stats: list[dict[str, float]] = []

    for idx in range(n_bins):
        upper_inclusive = idx == n_bins - 1
        mask = (probabilities >= bins[idx]) & (
            probabilities <= bins[idx + 1] if upper_inclusive else probabilities < bins[idx + 1]
        )
        count = int(mask.sum())
        if count == 0:
            bin_stats.append({"mean_pred": 0.0, "mean_true": 0.0, "count": 0})
            continue
        bin_stats.append(
            {
                "mean_pred": round(float(probabilities[mask].mean()), 4),
                "mean_true": round(float(labels[mask].mean()), 4),
                "count": count,
            }
        )

    return {
        "ece": round(_ece_value(labels, probabilities, n_bins=n_bins), 6),
        "n_bins": n_bins,
        "bin_stats": bin_stats,
    }
