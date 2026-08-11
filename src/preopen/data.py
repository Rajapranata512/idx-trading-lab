from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


REQUIRED_COLUMNS = ["timestamp", "ticker", "previous_close", "iep", "iev"]
DEPTH_COLUMNS = [
    f"{side}_{kind}_{level}"
    for side in ("bid", "ask")
    for kind in ("price", "volume")
    for level in range(1, 6)
]
SESSION_START = time(8, 45, 0)
SESSION_END = time(8, 59, 59)


def _local_timestamp(value: Any, timezone: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return pd.NaT
    if ts.tzinfo is None:
        return ts.tz_localize(ZoneInfo(timezone))
    return ts.tz_convert(ZoneInfo(timezone))


def normalize_as_of(value: datetime | pd.Timestamp | str | None, timezone: str) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp.now(tz=ZoneInfo(timezone))
    return _local_timestamp(value, timezone)


def canonicalize_preopen_snapshots(
    snapshots: pd.DataFrame,
    timezone: str = "Asia/Jakarta",
    require_market_depth: bool = True,
) -> pd.DataFrame:
    required = list(REQUIRED_COLUMNS)
    if require_market_depth:
        required.extend(DEPTH_COLUMNS)
    missing = sorted(set(required) - set(snapshots.columns))
    if missing:
        raise ValueError(f"Missing pre-open snapshot columns: {', '.join(missing)}")

    out = snapshots.copy()
    out["timestamp"] = out["timestamp"].map(lambda value: _local_timestamp(value, timezone))
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    numeric_columns = ["previous_close", "iep", "iev", "avg_daily_volume_20d", *DEPTH_COLUMNS]
    for column in numeric_columns:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")

    critical = ["timestamp", "ticker", "previous_close", "iep", "iev"]
    null_rows = out[critical].isna().any(axis=1) | out["ticker"].eq("")
    if null_rows.any():
        raise ValueError(f"Found {int(null_rows.sum())} pre-open rows with null critical values")
    if (out[["previous_close", "iep"]] <= 0).any(axis=None):
        raise ValueError("Pre-open previous_close and IEP must be positive")
    if (out["iev"] < 0).any():
        raise ValueError("Pre-open IEV cannot be negative")

    present_depth = [column for column in DEPTH_COLUMNS if column in out.columns]
    if present_depth:
        if out[present_depth].isna().any(axis=None):
            raise ValueError("Pre-open market-depth columns contain null values")
        if (out[present_depth] < 0).any(axis=None):
            raise ValueError("Pre-open market-depth values cannot be negative")

    if "source" not in out.columns:
        out["source"] = ""
    if "received_at" not in out.columns:
        out["received_at"] = out["timestamp"]
    else:
        out["received_at"] = out["received_at"].map(lambda value: _local_timestamp(value, timezone))
    if "rule_version" not in out.columns:
        out["rule_version"] = ""

    out = out.sort_values(["ticker", "timestamp", "received_at"])
    out = out.drop_duplicates(subset=["ticker", "timestamp"], keep="last")
    return out.reset_index(drop=True)


def validate_preopen_snapshots(
    snapshots: pd.DataFrame,
    timezone: str = "Asia/Jakarta",
    as_of: datetime | pd.Timestamp | str | None = None,
    session_date: date | str | None = None,
    require_market_depth: bool = True,
    max_snapshot_age_seconds: int = 20,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    as_of_ts = normalize_as_of(as_of, timezone)
    canonical = canonicalize_preopen_snapshots(
        snapshots=snapshots,
        timezone=timezone,
        require_market_depth=require_market_depth,
    )

    target_date = pd.Timestamp(session_date).date() if session_date is not None else as_of_ts.date()
    local_times = canonical["timestamp"].map(lambda ts: ts.timetz().replace(tzinfo=None))
    in_session = local_times.map(lambda value: SESSION_START <= value <= SESSION_END)
    same_date = canonical["timestamp"].map(lambda ts: ts.date() == target_date)
    not_future = canonical["timestamp"].le(as_of_ts)
    selected = canonical[in_session & same_date & not_future].copy()
    dropped_rows = int(len(canonical) - len(selected))

    latest = selected["timestamp"].max() if not selected.empty else pd.NaT
    age_seconds = None
    if pd.notna(latest):
        age_seconds = max(0.0, float((as_of_ts - latest).total_seconds()))
    stale = age_seconds is None or age_seconds > max(1, int(max_snapshot_age_seconds))
    sources = sorted({str(value).strip() for value in selected["source"] if str(value).strip()})
    report = {
        "ready": bool(not selected.empty and not stale),
        "rows": int(len(selected)),
        "tickers": int(selected["ticker"].nunique()) if not selected.empty else 0,
        "session_date": target_date.isoformat(),
        "as_of": as_of_ts.isoformat(),
        "latest_timestamp": pd.Timestamp(latest).isoformat() if pd.notna(latest) else "",
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "stale": bool(stale),
        "max_snapshot_age_seconds": int(max_snapshot_age_seconds),
        "dropped_rows": dropped_rows,
        "sources": sources,
        "require_market_depth": bool(require_market_depth),
    }
    return selected.reset_index(drop=True), report