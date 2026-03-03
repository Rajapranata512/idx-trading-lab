from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _to_numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series([float("nan")] * len(frame), index=frame.index, dtype="float64")


def _persist_settings_targets(settings_path: str | Path, atr_pct: float, realized_pct: float) -> None:
    path = Path(settings_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Settings payload must be a JSON object")
    if "risk" not in payload or not isinstance(payload["risk"], dict):
        raise ValueError("Settings payload missing 'risk' object")

    payload["risk"]["volatility_reference_atr_pct"] = float(round(atr_pct, 4))
    payload["risk"]["volatility_reference_realized_pct"] = float(round(realized_pct, 4))
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def maybe_auto_recalibrate_volatility_targets(
    settings: Settings,
    settings_path: str | Path | None = None,
    force: bool = False,
    features_path: str | Path = "data/processed/features.parquet",
) -> dict[str, Any]:
    risk = settings.risk
    enabled = bool(getattr(risk, "volatility_auto_recalibration_enabled", True))
    state_path = Path(getattr(risk, "volatility_auto_recalibration_state_path", "reports/volatility_recalibration_state.json"))
    now = datetime.utcnow()
    state = _read_state(state_path)

    result: dict[str, Any] = {
        "enabled": enabled,
        "forced": bool(force),
        "status": "skipped_disabled",
        "message": "Volatility auto-recalibration disabled",
        "updated": False,
        "attempted_at": now.isoformat(),
        "last_success_at": state.get("last_success_at", ""),
        "state_path": str(state_path),
        "features_path": str(features_path),
        "samples": {
            "rows_total": 0,
            "rows_window": 0,
            "atr_rows": 0,
            "realized_rows": 0,
            "lookback_days": int(getattr(risk, "volatility_auto_recalibration_lookback_days", 252)),
        },
        "old_targets": {
            "volatility_reference_atr_pct": float(risk.volatility_reference_atr_pct),
            "volatility_reference_realized_pct": float(getattr(risk, "volatility_reference_realized_pct", 2.0)),
        },
        "new_targets": {
            "volatility_reference_atr_pct": float(risk.volatility_reference_atr_pct),
            "volatility_reference_realized_pct": float(getattr(risk, "volatility_reference_realized_pct", 2.0)),
        },
    }

    if (not enabled) and (not force):
        return result

    last_success = pd.to_datetime(state.get("last_success_at"), errors="coerce")
    interval_days = max(1, int(getattr(risk, "volatility_auto_recalibration_interval_days", 7)))
    if (not force) and pd.notna(last_success):
        elapsed = now - pd.Timestamp(last_success).to_pydatetime()
        if elapsed < timedelta(days=interval_days):
            result["status"] = "skipped_interval"
            result["message"] = f"Last successful recalibration still within {interval_days} days interval"
            return result

    fpath = Path(features_path)
    if not fpath.exists():
        result["status"] = "skipped_no_features"
        result["message"] = f"Features file not found: {fpath}"
        return result

    feats = pd.read_parquet(fpath)
    result["samples"]["rows_total"] = int(len(feats))
    if feats.empty:
        result["status"] = "failed_empty_features"
        result["message"] = "Features file is empty"
        return result

    feats = feats.copy()
    feats["date"] = pd.to_datetime(feats.get("date"), errors="coerce")
    feats = feats.dropna(subset=["date"])
    if feats.empty:
        result["status"] = "failed_no_valid_dates"
        result["message"] = "Features has no valid 'date' rows"
        return result

    lookback_days = max(30, int(getattr(risk, "volatility_auto_recalibration_lookback_days", 252)))
    max_date = pd.Timestamp(feats["date"].max()).normalize()
    cutoff = max_date - pd.Timedelta(days=lookback_days)
    window = feats[feats["date"] >= cutoff].copy()
    result["samples"]["rows_window"] = int(len(window))
    if window.empty:
        result["status"] = "failed_no_rows_window"
        result["message"] = f"No rows in lookback window ({lookback_days} days)"
        return result

    atr_series = _to_numeric_series(window, "atr_pct").abs()
    atr_series = atr_series.replace([float("inf"), float("-inf")], float("nan")).dropna()
    atr_series = atr_series[atr_series > 0]

    realized_series = _to_numeric_series(window, "realized_vol_pct").abs()
    if realized_series.dropna().empty:
        realized_series = _to_numeric_series(window, "vol_20d").abs() * 100.0
    realized_series = realized_series.replace([float("inf"), float("-inf")], float("nan")).dropna()
    realized_series = realized_series[realized_series > 0]
    if not realized_series.empty and float(realized_series.median()) <= 1.0:
        realized_series = realized_series * 100.0

    result["samples"]["atr_rows"] = int(len(atr_series))
    result["samples"]["realized_rows"] = int(len(realized_series))
    min_rows = max(30, int(getattr(risk, "volatility_auto_recalibration_min_rows", 200)))
    if len(atr_series) < min_rows or len(realized_series) < min_rows:
        result["status"] = "failed_insufficient_samples"
        result["message"] = (
            f"Insufficient rows for recalibration (atr={len(atr_series)}, realized={len(realized_series)}, min={min_rows})"
        )
        return result

    q_atr = float(getattr(risk, "volatility_auto_recalibration_quantile_atr", 0.5))
    q_realized = float(getattr(risk, "volatility_auto_recalibration_quantile_realized", 0.5))
    q_atr = _clip(q_atr, 0.1, 0.9)
    q_realized = _clip(q_realized, 0.1, 0.9)

    raw_atr = float(atr_series.quantile(q_atr))
    raw_realized = float(realized_series.quantile(q_realized))

    min_atr = float(getattr(risk, "volatility_auto_recalibration_min_atr_pct", 1.5))
    max_atr = float(getattr(risk, "volatility_auto_recalibration_max_atr_pct", 8.0))
    min_realized = float(getattr(risk, "volatility_auto_recalibration_min_realized_pct", 0.8))
    max_realized = float(getattr(risk, "volatility_auto_recalibration_max_realized_pct", 6.0))
    if min_atr > max_atr:
        min_atr, max_atr = max_atr, min_atr
    if min_realized > max_realized:
        min_realized, max_realized = max_realized, min_realized

    new_atr = _clip(raw_atr, min_atr, max_atr)
    new_realized = _clip(raw_realized, min_realized, max_realized)

    old_atr = float(risk.volatility_reference_atr_pct)
    old_realized = float(getattr(risk, "volatility_reference_realized_pct", 2.0))
    delta_atr = abs(new_atr - old_atr)
    delta_realized = abs(new_realized - old_realized)
    min_delta = max(0.0, float(getattr(risk, "volatility_auto_recalibration_min_delta_pct", 0.05)))

    # Update in-memory runtime settings regardless of persistence target.
    risk.volatility_reference_atr_pct = float(round(new_atr, 4))
    risk.volatility_reference_realized_pct = float(round(new_realized, 4))
    result["new_targets"] = {
        "volatility_reference_atr_pct": float(round(new_atr, 4)),
        "volatility_reference_realized_pct": float(round(new_realized, 4)),
    }
    result["quantiles"] = {
        "atr_q": q_atr,
        "realized_q": q_realized,
        "raw_atr_pct": float(round(raw_atr, 4)),
        "raw_realized_pct": float(round(raw_realized, 4)),
    }
    result["bounds"] = {
        "atr_pct": [float(min_atr), float(max_atr)],
        "realized_pct": [float(min_realized), float(max_realized)],
    }
    result["delta"] = {
        "atr_pct": float(round(delta_atr, 4)),
        "realized_pct": float(round(delta_realized, 4)),
        "min_delta_pct": float(round(min_delta, 4)),
    }

    changed = (delta_atr >= min_delta) or (delta_realized >= min_delta)
    if not changed:
        result["status"] = "unchanged"
        result["message"] = "Recalibration completed with no meaningful target change"
        result["updated"] = False
        _write_state(
            state_path,
            {
                "last_attempt_at": now.isoformat(),
                "last_success_at": now.isoformat(),
                "status": result["status"],
                "message": result["message"],
                "new_targets": result["new_targets"],
                "delta": result["delta"],
                "samples": result["samples"],
            },
        )
        result["last_success_at"] = now.isoformat()
        return result

    if settings_path:
        _persist_settings_targets(settings_path=settings_path, atr_pct=new_atr, realized_pct=new_realized)
        result["settings_path"] = str(settings_path)

    result["status"] = "updated"
    result["message"] = "Volatility reference targets recalibrated"
    result["updated"] = True
    result["last_success_at"] = now.isoformat()
    _write_state(
        state_path,
        {
            "last_attempt_at": now.isoformat(),
            "last_success_at": now.isoformat(),
            "status": result["status"],
            "message": result["message"],
            "new_targets": result["new_targets"],
            "old_targets": result["old_targets"],
            "delta": result["delta"],
            "quantiles": result["quantiles"],
            "samples": result["samples"],
            "settings_path": result.get("settings_path", ""),
        },
    )
    return result
