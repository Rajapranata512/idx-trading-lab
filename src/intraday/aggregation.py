from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


REQUIRED_COLUMNS = ["timestamp", "ticker", "open", "high", "low", "close", "volume"]


def _local_timestamp(value: Any, timezone: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return pd.NaT
    if ts.tzinfo is None:
        return ts.tz_localize(ZoneInfo(timezone))
    return ts.tz_convert(ZoneInfo(timezone))


def _session_anchor(ts: pd.Timestamp) -> pd.Timestamp | None:
    if ts.weekday() >= 5:
        return None
    clock = ts.timetz().replace(tzinfo=None)
    morning_end = time(11, 30) if ts.weekday() == 4 else time(12, 0)
    afternoon_start = time(14, 0) if ts.weekday() == 4 else time(13, 30)
    if time(9, 0) <= clock < morning_end:
        anchor = time(9, 0)
    elif afternoon_start <= clock < time(15, 50):
        anchor = afternoon_start
    else:
        return None
    return pd.Timestamp(datetime.combine(ts.date(), anchor), tz=ts.tzinfo)


def aggregate_5m_to_15m(
    prices: pd.DataFrame,
    timezone: str = "Asia/Jakarta",
    require_complete_bars: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    missing = sorted(set(REQUIRED_COLUMNS) - set(prices.columns))
    if missing:
        raise ValueError(f"Missing intraday aggregation columns: {', '.join(missing)}")
    frame = prices.copy()
    frame["timestamp"] = frame["timestamp"].map(lambda value: _local_timestamp(value, timezone))
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=REQUIRED_COLUMNS).copy()
    before_dedupe = len(frame)
    frame = frame.sort_values(["ticker", "timestamp"]).drop_duplicates(
        subset=["ticker", "timestamp"],
        keep="last",
    )
    duplicate_rows = int(before_dedupe - len(frame))

    frame["session_anchor"] = frame["timestamp"].map(_session_anchor)
    outside_session_rows = int(frame["session_anchor"].isna().sum())
    frame = frame.dropna(subset=["session_anchor"]).copy()
    if frame.empty:
        return pd.DataFrame(columns=[*REQUIRED_COLUMNS, "timeframe", "source", "source_bar_count"]), {
            "input_rows": int(len(prices)),
            "output_rows": 0,
            "duplicate_rows": duplicate_rows,
            "outside_session_rows": outside_session_rows,
            "partial_bars_dropped": 0,
        }

    elapsed_minutes = (frame["timestamp"] - frame["session_anchor"]).dt.total_seconds() // 60
    frame["bucket_start"] = frame["session_anchor"] + pd.to_timedelta(
        (elapsed_minutes // 15) * 15,
        unit="m",
    )
    grouped = frame.groupby(["ticker", "bucket_start"], sort=True)
    rows: list[dict[str, Any]] = []
    partial_bars = 0
    for (ticker, bucket_start), group in grouped:
        group = group.sort_values("timestamp")
        offsets = sorted(
            int((timestamp - bucket_start).total_seconds() // 60)
            for timestamp in group["timestamp"].unique()
        )
        complete = offsets == [0, 5, 10]
        if require_complete_bars and not complete:
            partial_bars += 1
            continue
        rows.append(
            {
                "timestamp": bucket_start,
                "ticker": ticker,
                "open": float(group.iloc[0]["open"]),
                "high": float(group["high"].max()),
                "low": float(group["low"].min()),
                "close": float(group.iloc[-1]["close"]),
                "volume": float(group["volume"].sum()),
                "timeframe": "15m",
                "source": "aggregated_5m",
                "source_bar_count": int(len(group)),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["ticker", "timestamp"]).reset_index(drop=True)
    return out, {
        "input_rows": int(len(prices)),
        "output_rows": int(len(out)),
        "duplicate_rows": duplicate_rows,
        "outside_session_rows": outside_session_rows,
        "partial_bars_dropped": int(partial_bars),
        "source_timeframe": "5m",
        "model_timeframe": "15m",
        "require_complete_bars": bool(require_complete_bars),
    }