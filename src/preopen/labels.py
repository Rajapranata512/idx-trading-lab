from __future__ import annotations

from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.preopen.data import canonicalize_preopen_snapshots


LABEL_VERSION = "preopen_open_follow_v1"


def _normalize_bar_timestamp(value: Any, timezone: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return pd.NaT
    if ts.tzinfo is None:
        return ts.tz_localize(ZoneInfo(timezone))
    return ts.tz_convert(ZoneInfo(timezone))


def _close_for_horizon(bars: pd.DataFrame, minutes: int) -> tuple[float, pd.Timestamp] | None:
    if bars.empty:
        return None
    opening_ts = bars["timestamp"].iloc[0]
    eligible = bars[bars["timestamp"] < opening_ts + pd.Timedelta(minutes=max(1, int(minutes)))]
    if eligible.empty:
        return None
    row = eligible.iloc[-1]
    return float(row["close"]), row["timestamp"]


def build_preopen_labels(
    snapshots: pd.DataFrame,
    intraday_bars: pd.DataFrame,
    timezone: str = "Asia/Jakarta",
    decision_cutoff_time_local: str = "08:57:40",
    roundtrip_cost_bps: float = 65.0,
    minimum_edge_bps: float = 10.0,
    fake_reversal_bps: float = 10.0,
) -> pd.DataFrame:
    canonical = canonicalize_preopen_snapshots(
        snapshots,
        timezone=timezone,
        require_market_depth=False,
    )
    if canonical.empty or intraday_bars.empty:
        return pd.DataFrame()

    bars = intraday_bars.copy()
    timestamp_column = "timestamp" if "timestamp" in bars.columns else "date"
    required_bar_columns = {timestamp_column, "ticker", "open", "high", "low", "close"}
    missing = sorted(required_bar_columns - set(bars.columns))
    if missing:
        raise ValueError(f"Missing intraday label columns: {', '.join(missing)}")
    bars["timestamp"] = bars[timestamp_column].map(lambda value: _normalize_bar_timestamp(value, timezone))
    bars["ticker"] = bars["ticker"].astype(str).str.upper().str.strip()
    for column in ["open", "high", "low", "close"]:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    bars = bars.dropna(subset=["timestamp", "ticker", "open", "high", "low", "close"])
    bars = bars[bars["timestamp"].map(lambda ts: ts.timetz().replace(tzinfo=None) >= time(9, 0))]
    bars["session_date"] = bars["timestamp"].map(lambda ts: ts.date().isoformat())

    cutoff_clock = pd.Timestamp(decision_cutoff_time_local).time()
    canonical = canonical[
        canonical["timestamp"].map(lambda ts: ts.timetz().replace(tzinfo=None) <= cutoff_clock)
    ].copy()
    canonical["session_date"] = canonical["timestamp"].map(lambda ts: ts.date().isoformat())
    latest = canonical.sort_values("timestamp").groupby(["session_date", "ticker"], as_index=False).tail(1)

    rows: list[dict[str, Any]] = []
    cost_bps = max(0.0, float(roundtrip_cost_bps))
    edge_bps = float(minimum_edge_bps)
    fake_bps = max(0.0, float(fake_reversal_bps))
    for _, snapshot in latest.iterrows():
        session_date = str(snapshot["session_date"])
        ticker = str(snapshot["ticker"])
        ticker_bars = bars[(bars["session_date"] == session_date) & (bars["ticker"] == ticker)].sort_values("timestamp")
        if ticker_bars.empty:
            continue
        close_5 = _close_for_horizon(ticker_bars, 5)
        close_15 = _close_for_horizon(ticker_bars, 15)
        if close_5 is None or close_15 is None:
            continue

        opening = float(ticker_bars.iloc[0]["open"])
        previous_close = float(snapshot["previous_close"])
        iep = float(snapshot["iep"])
        close_5_price, close_5_ts = close_5
        close_15_price, close_15_ts = close_15
        open_gap_bps = ((opening - previous_close) / previous_close) * 10000.0
        iep_gap_bps = ((iep - previous_close) / previous_close) * 10000.0
        long_5_bps = ((close_5_price - opening) / opening) * 10000.0
        long_15_bps = ((close_15_price - opening) / opening) * 10000.0
        short_15_bps = -long_15_bps
        window_15 = ticker_bars[ticker_bars["timestamp"] < ticker_bars["timestamp"].iloc[0] + pd.Timedelta(minutes=15)]
        max_high = float(window_15["high"].max())
        min_low = float(window_15["low"].min())

        rows.append(
            {
                "session_date": session_date,
                "ticker": ticker,
                "cutoff_timestamp": snapshot["timestamp"].isoformat(),
                "label_version": LABEL_VERSION,
                "previous_close": previous_close,
                "final_iep": iep,
                "final_iev": float(snapshot["iev"]),
                "opening_price": opening,
                "close_5m": close_5_price,
                "close_15m": close_15_price,
                "close_5m_timestamp": close_5_ts.isoformat(),
                "close_15m_timestamp": close_15_ts.isoformat(),
                "iep_gap_bps": round(iep_gap_bps, 6),
                "open_gap_bps": round(open_gap_bps, 6),
                "gross_return_open_5m_bps": round(long_5_bps, 6),
                "gross_return_open_15m_bps": round(long_15_bps, 6),
                "net_return_open_5m_bps": round(long_5_bps - cost_bps, 6),
                "net_return_open_15m_bps": round(long_15_bps - cost_bps, 6),
                "net_short_return_open_15m_bps": round(short_15_bps - cost_bps, 6),
                "mae_open_15m_bps": round(((min_low - opening) / opening) * 10000.0, 6),
                "mfe_open_15m_bps": round(((max_high - opening) / opening) * 10000.0, 6),
                "y_open_up": int(opening > previous_close),
                "y_follow_up_5m": int((long_5_bps - cost_bps) > edge_bps),
                "y_follow_up_15m": int((long_15_bps - cost_bps) > edge_bps),
                "y_follow_down_15m": int((short_15_bps - cost_bps) > edge_bps),
                "y_fake_gap_up_15m": int(
                    iep_gap_bps >= fake_bps
                    and (close_15_price <= previous_close or long_15_bps <= -fake_bps)
                ),
                "y_fake_gap_down_15m": int(
                    iep_gap_bps <= -fake_bps
                    and (close_15_price >= previous_close or long_15_bps >= fake_bps)
                ),
            }
        )

    return pd.DataFrame(rows).sort_values(["session_date", "ticker"]).reset_index(drop=True) if rows else pd.DataFrame()