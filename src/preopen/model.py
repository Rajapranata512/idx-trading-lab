from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.config import PreopenAuctionSettings


CLASSIFIER_TARGETS = [
    "open_up",
    "follow_up_15m",
    "follow_down_15m",
    "fake_gap_up_15m",
    "fake_gap_down_15m",
]
REGRESSION_TARGET = "expected_return_15m_bps"
REQUIRED_THRESHOLDS = [
    "p_open_up_min",
    "p_open_down_min",
    "p_follow_min",
    "p_fake_max",
    "p_fake_alert_min",
    "expected_return_up_min_bps",
    "expected_return_down_max_bps",
]


def _artifact_paths(model_dir: str | Path) -> tuple[Path, Path]:
    root = Path(model_dir)
    return root / "preopen_auction.joblib", root / "preopen_auction.meta.json"


def load_preopen_bundle(model_dir: str | Path) -> tuple[Any | None, dict[str, Any], str]:
    artifact_path, metadata_path = _artifact_paths(model_dir)
    if not artifact_path.exists() or artifact_path.stat().st_size <= 0:
        return None, {}, "model_artifact_missing"
    if not metadata_path.exists() or metadata_path.stat().st_size <= 0:
        return None, {}, "model_metadata_missing"
    try:
        bundle = joblib.load(artifact_path)
    except Exception as exc:
        return None, {}, f"model_artifact_unloadable:{type(exc).__name__}"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, {}, f"model_metadata_invalid:{type(exc).__name__}"
    return bundle, metadata if isinstance(metadata, dict) else {}, ""


def _metadata_gate(metadata: dict[str, Any], settings: PreopenAuctionSettings) -> tuple[bool, list[str]]:
    failures: list[str] = []
    features = metadata.get("feature_columns", [])
    thresholds = metadata.get("thresholds", {})
    if not isinstance(features, list) or not features:
        failures.append("feature_contract_missing")
    if not isinstance(thresholds, dict) or any(key not in thresholds for key in REQUIRED_THRESHOLDS):
        failures.append("threshold_contract_missing")
    if metadata.get("calibrated") is not True:
        failures.append("calibration_missing")
    if metadata.get("evaluated_on_holdout") is not True:
        failures.append("holdout_evaluation_missing")
    ece_pct = float(metadata.get("ece_pct", np.inf))
    if not np.isfinite(ece_pct) or ece_pct > float(settings.max_calibration_ece_pct):
        failures.append("calibration_ece_failed")
    if int(metadata.get("oos_samples", 0) or 0) < int(settings.min_oos_samples):
        failures.append("oos_samples_insufficient")
    if int(metadata.get("walk_forward_folds", 0) or 0) < int(settings.min_walk_forward_folds):
        failures.append("walk_forward_folds_insufficient")
    if not str(metadata.get("label_version", "")).strip():
        failures.append("label_version_missing")
    if not str(metadata.get("rule_version", "")).strip():
        failures.append("rule_version_missing")
    if str(metadata.get("decision_cutoff_time_local", "")).strip() != str(settings.decision_cutoff_time_local):
        failures.append("decision_cutoff_mismatch")
    return not failures, failures


def _bundle_gate(bundle: Any) -> tuple[bool, list[str]]:
    if not isinstance(bundle, dict):
        return False, ["artifact_bundle_invalid"]
    models = bundle.get("models")
    if not isinstance(models, dict):
        return False, ["artifact_models_missing"]
    failures: list[str] = []
    for target in CLASSIFIER_TARGETS:
        model = models.get(target)
        if model is None or not callable(getattr(model, "predict_proba", None)):
            failures.append(f"classifier_missing:{target}")
    regressor = models.get(REGRESSION_TARGET)
    if regressor is None or not callable(getattr(regressor, "predict", None)):
        failures.append(f"regressor_missing:{REGRESSION_TARGET}")
    return not failures, failures


def _blocked_output(features: pd.DataFrame, reason: str, failures: list[str] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    out = features.copy()
    out["shadow_classification"] = "NO_TRADE"
    out["shadow_watch_up"] = False
    out["shadow_avoid"] = True
    out["shadow_model_source"] = "unavailable"
    out["shadow_block_reason"] = reason
    out["final_decision"] = False
    out["execution_authorized"] = False
    return out, {
        "status": "blocked",
        "ready": False,
        "message": reason,
        "failures": failures or [reason],
    }


def infer_preopen_shadow(
    features: pd.DataFrame,
    settings: PreopenAuctionSettings,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if features.empty:
        return _blocked_output(features, "no_preopen_features")

    bundle, metadata, load_error = load_preopen_bundle(settings.model_dir)
    if load_error:
        return _blocked_output(features, load_error)
    bundle_ok, bundle_failures = _bundle_gate(bundle)
    metadata_ok, metadata_failures = _metadata_gate(metadata, settings)
    failures = [*bundle_failures, *metadata_failures]
    if not bundle_ok or not metadata_ok:
        return _blocked_output(features, "preopen_model_contract_blocked", failures)

    feature_columns = [str(column) for column in metadata["feature_columns"]]
    missing_features = sorted(set(feature_columns) - set(features.columns))
    if missing_features:
        return _blocked_output(
            features,
            "preopen_feature_contract_mismatch",
            [f"missing_feature:{column}" for column in missing_features],
        )
    x = features[feature_columns].apply(pd.to_numeric, errors="coerce")
    if x.isna().any(axis=None):
        return _blocked_output(features, "preopen_features_contain_null")

    models = bundle["models"]
    out = features.copy()
    try:
        for target in CLASSIFIER_TARGETS:
            probabilities = np.asarray(models[target].predict_proba(x), dtype=float)
            if probabilities.ndim != 2 or probabilities.shape[1] < 2:
                raise ValueError(f"invalid_predict_proba_shape:{target}")
            out[f"p_{target}"] = np.clip(probabilities[:, 1], 0.0, 1.0)
        out["expected_return_15m_bps"] = np.asarray(
            models[REGRESSION_TARGET].predict(x),
            dtype=float,
        )
    except Exception as exc:
        return _blocked_output(features, f"preopen_model_inference_error:{type(exc).__name__}")

    thresholds = {key: float(metadata["thresholds"][key]) for key in REQUIRED_THRESHOLDS}
    classifications: list[str] = []
    watch_up: list[bool] = []
    avoid: list[bool] = []
    for _, row in out.iterrows():
        data_ready = bool(row.get("data_ready", False))
        up = (
            data_ready
            and float(row["p_open_up"]) >= thresholds["p_open_up_min"]
            and float(row["p_follow_up_15m"]) >= thresholds["p_follow_min"]
            and float(row["p_fake_gap_up_15m"]) <= thresholds["p_fake_max"]
            and float(row["expected_return_15m_bps"]) >= thresholds["expected_return_up_min_bps"]
        )
        down = (
            data_ready
            and (1.0 - float(row["p_open_up"])) >= thresholds["p_open_down_min"]
            and float(row["p_follow_down_15m"]) >= thresholds["p_follow_min"]
            and float(row["p_fake_gap_down_15m"]) <= thresholds["p_fake_max"]
            and float(row["expected_return_15m_bps"]) <= thresholds["expected_return_down_max_bps"]
        )
        fake_up = data_ready and float(row["iep_gap_bps"]) > 0 and float(row["p_fake_gap_up_15m"]) >= thresholds["p_fake_alert_min"]
        fake_down = data_ready and float(row["iep_gap_bps"]) < 0 and float(row["p_fake_gap_down_15m"]) >= thresholds["p_fake_alert_min"]
        if up:
            classification = "UP_FOLLOW_THROUGH"
        elif down:
            classification = "DOWN_FOLLOW_THROUGH"
        elif fake_up:
            classification = "FAKE_UP_RISK"
        elif fake_down:
            classification = "FAKE_DOWN_RISK"
        else:
            classification = "UNCERTAIN" if data_ready else "NO_TRADE"
        classifications.append(classification)
        watch_up.append(classification == "UP_FOLLOW_THROUGH")
        avoid.append(classification in {"DOWN_FOLLOW_THROUGH", "FAKE_UP_RISK", "NO_TRADE"})

    out["p_open_down"] = 1.0 - out["p_open_up"]
    out["shadow_classification"] = classifications
    out["shadow_watch_up"] = watch_up
    out["shadow_avoid"] = avoid
    out["shadow_model_source"] = "model"
    out["shadow_block_reason"] = ""
    out["model_version"] = str(metadata.get("model_version", ""))
    out["final_decision"] = False
    out["execution_authorized"] = False
    out = out.sort_values(
        ["shadow_watch_up", "p_follow_up_15m", "expected_return_15m_bps", "ticker"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)
    out["shadow_rank"] = range(1, len(out) + 1)
    return out, {
        "status": "ready",
        "ready": True,
        "message": "Pre-open shadow inference completed",
        "model_version": str(metadata.get("model_version", "")),
        "label_version": str(metadata.get("label_version", "")),
        "rule_version": str(metadata.get("rule_version", "")),
        "calibrated": True,
        "evaluated_on_holdout": True,
        "ece_pct": float(metadata.get("ece_pct")),
        "oos_samples": int(metadata.get("oos_samples")),
        "walk_forward_folds": int(metadata.get("walk_forward_folds")),
        "thresholds": thresholds,
        "final_decision": False,
        "execution_authorized": False,
    }