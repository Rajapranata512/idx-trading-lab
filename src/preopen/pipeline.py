from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import Settings
from src.preopen.data import normalize_as_of, validate_preopen_snapshots
from src.preopen.features import build_preopen_features
from src.preopen.model import infer_preopen_shadow
from src.utils.io import atomic_write_json


def _clock_on_date(base: pd.Timestamp, clock_value: str) -> pd.Timestamp:
    parsed = pd.Timestamp(clock_value).time()
    return pd.Timestamp(
        datetime.combine(base.date(), parsed),
        tz=base.tzinfo or ZoneInfo("Asia/Jakarta"),
    )


def _phase(as_of: pd.Timestamp, preliminary: pd.Timestamp, cutoff: pd.Timestamp, market_open: pd.Timestamp) -> str:
    if as_of < preliminary:
        return "before_preliminary"
    if as_of < cutoff:
        return "preliminary"
    if as_of < market_open:
        return "final_preopen"
    return "post_open"


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    clean = frame.astype(object).where(pd.notna(frame), None)
    return clean.to_dict(orient="records")


def _write_report(path: str | Path, payload: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return atomic_write_json(target, payload)


def _blocked_report(
    settings: Settings,
    as_of: pd.Timestamp,
    phase: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "as_of": as_of.isoformat(),
        "phase": phase,
        "status": "blocked",
        "shadow_only": True,
        "final_decision": False,
        "execution_status": "EXECUTION_DISABLED",
        "block_reason": reason,
        "details": details or {},
        "signals": [],
    }
    _write_report(settings.preopen_auction.report_path, payload)
    return payload


def run_preopen_auction_shadow(
    settings: Settings,
    snapshots_path: str | Path | None = None,
    as_of: datetime | pd.Timestamp | str | None = None,
) -> dict[str, Any]:
    cfg = settings.preopen_auction
    as_of_ts = normalize_as_of(as_of, settings.data.timezone)
    preliminary_ts = _clock_on_date(as_of_ts, cfg.preliminary_time_local)
    cutoff_ts = _clock_on_date(as_of_ts, cfg.decision_cutoff_time_local)
    market_open_ts = _clock_on_date(as_of_ts, cfg.market_open_time_local)
    phase = _phase(as_of_ts, preliminary_ts, cutoff_ts, market_open_ts)

    if not cfg.enabled:
        return _blocked_report(settings, as_of_ts, phase, "preopen_auction_disabled")
    if not cfg.shadow_only:
        return _blocked_report(settings, as_of_ts, phase, "preopen_must_remain_shadow_only")
    if not cfg.data_license_confirmed or not cfg.retention_allowed:
        return _blocked_report(settings, as_of_ts, phase, "preopen_data_license_not_confirmed")
    if not str(cfg.provider_name).strip():
        return _blocked_report(settings, as_of_ts, phase, "preopen_provider_missing")

    source_path = Path(snapshots_path or cfg.snapshots_path)
    if not source_path.exists() or source_path.stat().st_size <= 0:
        return _blocked_report(
            settings,
            as_of_ts,
            phase,
            "preopen_snapshot_file_missing",
            {"path": str(source_path)},
        )

    analysis_as_of = min(as_of_ts, cutoff_ts)
    try:
        raw = pd.read_csv(source_path)
        snapshots, data_quality = validate_preopen_snapshots(
            snapshots=raw,
            timezone=settings.data.timezone,
            as_of=analysis_as_of,
            require_market_depth=bool(cfg.require_market_depth),
            max_snapshot_age_seconds=int(cfg.max_snapshot_age_seconds),
        )
    except Exception as exc:
        return _blocked_report(
            settings,
            as_of_ts,
            phase,
            f"preopen_data_validation_error:{type(exc).__name__}",
            {"message": str(exc), "path": str(source_path)},
        )

    features = build_preopen_features(
        snapshots=snapshots,
        as_of=analysis_as_of,
        timezone=settings.data.timezone,
        min_snapshots_per_ticker=int(cfg.min_snapshots_per_ticker),
        max_snapshot_age_seconds=int(cfg.max_snapshot_age_seconds),
    )
    features_path = Path(cfg.features_path)
    features_path.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(features_path, index=False)

    try:
        scored, model_status = infer_preopen_shadow(features, cfg)
    except Exception as exc:
        scored = features.copy()
        scored["shadow_classification"] = "NO_TRADE"
        scored["shadow_watch_up"] = False
        scored["shadow_avoid"] = True
        scored["final_decision"] = False
        scored["execution_authorized"] = False
        model_status = {
            "status": "blocked",
            "ready": False,
            "message": f"preopen_model_contract_error:{type(exc).__name__}",
            "failures": ["preopen_model_contract_invalid"],
        }
    data_ready = bool(data_quality.get("ready")) and bool(
        not features.empty and features["data_ready"].fillna(False).any()
    )
    model_ready = bool(model_status.get("ready"))
    overall_status = "ready" if data_ready and model_ready else "blocked"
    block_reasons: list[str] = []
    if not data_ready:
        block_reasons.append("preopen_data_not_ready")
    if not model_ready:
        block_reasons.extend(str(value) for value in model_status.get("failures", []) if str(value))

    payload = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "as_of": as_of_ts.isoformat(),
        "analysis_cutoff": analysis_as_of.isoformat(),
        "phase": phase,
        "status": overall_status,
        "shadow_only": True,
        "final_decision": False,
        "execution_status": "EXECUTION_DISABLED",
        "provider_name": str(cfg.provider_name),
        "data_license_confirmed": bool(cfg.data_license_confirmed),
        "retention_allowed": bool(cfg.retention_allowed),
        "source_path": str(source_path).replace("\\", "/"),
        "features_path": str(features_path).replace("\\", "/"),
        "data_quality": data_quality,
        "model": model_status,
        "block_reasons": sorted(set(block_reasons)),
        "summary": {
            "total": int(len(scored)),
            "watch_up": int(scored.get("shadow_watch_up", pd.Series(dtype=bool)).fillna(False).sum()),
            "avoid": int(scored.get("shadow_avoid", pd.Series(dtype=bool)).fillna(False).sum()),
            "no_trade": int(scored.get("shadow_classification", pd.Series(dtype=str)).eq("NO_TRADE").sum()),
        },
        "signals": _records(scored),
    }
    _write_report(cfg.report_path, payload)
    return payload
