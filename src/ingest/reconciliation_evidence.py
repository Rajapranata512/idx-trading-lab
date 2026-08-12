from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import PriceQualitySettings


_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str, fallback: str) -> str:
    cleaned = _SAFE_NAME.sub("_", str(value).strip()).strip("._")
    return cleaned or fallback


def _canonical_snapshot(frame: pd.DataFrame | None, session_dates: list[str]) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    if "date" not in out.columns:
        return pd.DataFrame()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out = out.dropna(subset=["date"])
    if session_dates:
        out = out[out["date"].isin(session_dates)]
    sort_columns = [column for column in ["date", "ticker", "ingested_at"] if column in out.columns]
    if sort_columns:
        out = out.sort_values(sort_columns)
    dedupe_columns = [column for column in ["date", "ticker"] if column in out.columns]
    if len(dedupe_columns) == 2:
        out = out.drop_duplicates(subset=dedupe_columns, keep="last")
    return out.reset_index(drop=True)


def _write_snapshot(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_calendar(path: str | Path, market_date: date) -> tuple[set[date], str]:
    calendar_path = Path(path)
    if not calendar_path.exists():
        return set(), f"market calendar not found: {calendar_path}"
    try:
        payload = json.loads(calendar_path.read_text(encoding="utf-8"))
        valid_from = date.fromisoformat(str(payload.get("valid_from", "")))
        valid_until = date.fromisoformat(str(payload.get("valid_until", "")))
        if not valid_from <= market_date <= valid_until:
            return set(), "market date is outside calendar validity"
        holidays = {
            date.fromisoformat(str(row["date"]))
            for row in payload.get("holidays", [])
            if isinstance(row, dict) and row.get("date")
        }
        return holidays, ""
    except Exception as exc:
        return set(), f"market calendar invalid: {exc}"


def _expected_market_sessions(latest: date, count: int, holidays: set[date]) -> list[str]:
    sessions: list[date] = []
    cursor = latest
    while len(sessions) < max(1, int(count)):
        if cursor.weekday() < 5 and cursor not in holidays:
            sessions.append(cursor)
        cursor -= timedelta(days=1)
    return [value.isoformat() for value in reversed(sessions)]


def _load_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "sessions": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": 1, "sessions": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
        return {"schema_version": 1, "sessions": []}
    return payload


def record_price_reconciliation_evidence(
    *,
    config: PriceQualitySettings,
    primary: pd.DataFrame | None,
    reference: pd.DataFrame | None,
    details: pd.DataFrame,
    reconciliation: dict[str, Any],
    active_unresolved_count: int,
) -> dict[str, Any]:
    """Persist provider snapshots and evaluate the consecutive-session quality gate."""
    if not bool(config.reconciliation_evidence_enabled):
        return {"status": "disabled", "qualified": False}

    primary_dates = []
    if primary is not None and not primary.empty and "date" in primary.columns:
        primary_dates = sorted(
            pd.to_datetime(primary["date"], errors="coerce")
            .dropna()
            .dt.strftime("%Y-%m-%d")
            .unique()
            .tolist()
        )
    market_date_text = str(reconciliation.get("market_date", "")).strip()
    if not market_date_text and primary_dates:
        market_date_text = primary_dates[-1]
    try:
        market_date = date.fromisoformat(market_date_text)
    except ValueError:
        return {
            "status": "unavailable",
            "qualified": False,
            "message": "Reconciliation evidence has no valid market date",
        }

    session_dates = [str(value) for value in reconciliation.get("session_dates", []) if value]
    if not session_dates:
        session_dates = primary_dates[-max(1, int(config.reconciliation_lookback_sessions)) :]

    evidence_dir = Path(config.reconciliation_evidence_dir) / market_date.isoformat()
    primary_source = str(reconciliation.get("primary_source", ""))
    reference_source = str(reconciliation.get("reference_source", ""))
    primary_path = evidence_dir / f"primary_{_safe_name(primary_source, 'unknown')}.csv"
    reference_path = evidence_dir / f"reference_{_safe_name(reference_source, 'unavailable')}.csv"
    details_path = evidence_dir / "comparison.csv"
    summary_path = evidence_dir / "summary.json"

    primary_snapshot = _canonical_snapshot(primary, session_dates)
    reference_snapshot = _canonical_snapshot(reference, session_dates)
    primary_digest = _write_snapshot(primary_path, primary_snapshot)
    reference_digest = ""
    if not reference_snapshot.empty:
        reference_digest = _write_snapshot(reference_path, reference_snapshot)
    details_digest = _write_snapshot(details_path, details)

    required_primary = str(config.reconciliation_required_primary_source).strip()
    required_reference = str(config.reconciliation_required_reference_source).strip()
    coverage = float(reconciliation.get("coverage_ratio", 0.0) or 0.0)
    mismatch = float(reconciliation.get("mismatch_ratio", 1.0) or 0.0)
    reasons: list[str] = []
    if str(reconciliation.get("status", "")) != "pass":
        reasons.append("reconciliation_not_passed")
    if primary_source != required_primary:
        reasons.append("unexpected_primary_source")
    if reference_source != required_reference:
        reasons.append("unexpected_reference_source")
    if coverage < float(config.reconciliation_min_coverage_ratio):
        reasons.append("coverage_below_threshold")
    if mismatch > float(config.reconciliation_max_mismatch_ratio):
        reasons.append("mismatch_above_threshold")
    if int(active_unresolved_count) > 0:
        reasons.append("active_unresolved_price_anomaly")

    holidays, calendar_error = _load_calendar(
        config.reconciliation_market_calendar_path,
        market_date,
    )
    if calendar_error:
        reasons.append("market_calendar_unavailable")
    elif market_date.weekday() >= 5 or market_date in holidays:
        reasons.append("market_date_is_not_trading_session")

    session = {
        "market_date": market_date.isoformat(),
        "recorded_at": _utc_now(),
        "eligible": not reasons,
        "reasons": reasons,
        "status": str(reconciliation.get("status", "")),
        "primary_source": primary_source,
        "reference_source": reference_source,
        "coverage_ratio": coverage,
        "mismatch_ratio": mismatch,
        "active_unresolved_count": int(active_unresolved_count),
        "rows_compared": int(reconciliation.get("rows_compared", 0) or 0),
        "evidence": {
            "primary_path": str(primary_path),
            "primary_sha256": primary_digest,
            "reference_path": str(reference_path) if reference_digest else "",
            "reference_sha256": reference_digest,
            "comparison_path": str(details_path),
            "comparison_sha256": details_digest,
            "summary_path": str(summary_path),
        },
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(session, ensure_ascii=True, indent=2), encoding="utf-8")

    history_path = Path(config.reconciliation_evidence_history_path)
    history = _load_history(history_path)
    previous = [
        row
        for row in history.get("sessions", [])
        if isinstance(row, dict) and str(row.get("market_date", "")) != market_date.isoformat()
    ]
    sessions = sorted(previous + [session], key=lambda row: str(row.get("market_date", "")))
    retention = max(
        int(config.reconciliation_min_consecutive_sessions),
        int(config.reconciliation_evidence_retention_sessions),
    )
    sessions = sessions[-retention:]

    required_count = int(config.reconciliation_min_consecutive_sessions)
    expected_dates = (
        _expected_market_sessions(market_date, required_count, holidays)
        if not calendar_error
        else []
    )
    by_date = {str(row.get("market_date", "")): row for row in sessions}
    consecutive_passes = 0
    for expected in reversed(expected_dates):
        row = by_date.get(expected)
        if not row or not bool(row.get("eligible", False)):
            break
        consecutive_passes += 1
    missing_dates = [value for value in expected_dates if value not in by_date]
    failing_dates = [
        value
        for value in expected_dates
        if value in by_date and not bool(by_date[value].get("eligible", False))
    ]
    qualified = bool(
        not calendar_error
        and len(expected_dates) == required_count
        and consecutive_passes >= required_count
    )
    qualification = {
        "qualified": qualified,
        "required_consecutive_sessions": required_count,
        "consecutive_passes": consecutive_passes,
        "latest_market_date": market_date.isoformat(),
        "expected_session_dates": expected_dates,
        "missing_session_dates": missing_dates,
        "failing_session_dates": failing_dates,
        "calendar_error": calendar_error,
        "enforcement_enabled": bool(config.reconciliation_required),
    }
    history_payload = {
        "schema_version": 1,
        "updated_at": _utc_now(),
        "qualification": qualification,
        "sessions": sessions,
    }
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(history_payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return {
        "status": "qualified" if qualified else "collecting",
        "qualified": qualified,
        "history_path": str(history_path),
        "session": session,
        "qualification": qualification,
    }