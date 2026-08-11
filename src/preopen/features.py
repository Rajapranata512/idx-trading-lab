from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.preopen.data import DEPTH_COLUMNS, normalize_as_of


PREOPEN_FEATURE_COLUMNS = [
    "snapshot_count",
    "latest_age_seconds",
    "iep_gap_bps",
    "iep_change_from_first_bps",
    "iep_slope_bps_per_minute",
    "iep_volatility_bps",
    "iep_sign_flips",
    "iep_reversal_from_peak_bps",
    "iep_rebound_from_trough_bps",
    "iev_growth_pct",
    "iev_peak_retention",
    "iev_to_adv20_pct",
    "late_iep_change_bps",
    "late_iev_retention",
    "bid_ask_imbalance_l1",
    "bid_ask_imbalance_l5",
    "weighted_depth_imbalance",
    "spread_bps",
    "microprice_vs_iep_bps",
    "bid_depth_withdrawal_proxy",
    "ask_depth_withdrawal_proxy",
    "imbalance_stability",
]


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    if not np.isfinite(denominator) or abs(denominator) < 1e-12:
        return default
    return float(numerator / denominator)


def _withdrawal_proxy(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    if numeric.size < 2:
        return 0.0
    declines = np.maximum(numeric[:-1] - numeric[1:], 0.0).sum()
    baseline = np.maximum(numeric[:-1], 0.0).sum()
    return _safe_ratio(float(declines), float(baseline), 0.0)


def _depth_snapshot(row: pd.Series) -> dict[str, float]:
    bid_volumes = np.array([float(row.get(f"bid_volume_{level}", 0.0) or 0.0) for level in range(1, 6)])
    ask_volumes = np.array([float(row.get(f"ask_volume_{level}", 0.0) or 0.0) for level in range(1, 6)])
    bid_total = float(bid_volumes.sum())
    ask_total = float(ask_volumes.sum())
    l1_total = float(bid_volumes[0] + ask_volumes[0])
    weights = np.array([1.0, 0.8, 0.6, 0.4, 0.2])
    weighted_bid = float((bid_volumes * weights).sum())
    weighted_ask = float((ask_volumes * weights).sum())

    best_bid = float(row.get("bid_price_1", 0.0) or 0.0)
    best_ask = float(row.get("ask_price_1", 0.0) or 0.0)
    midpoint = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0
    spread_bps = _safe_ratio(best_ask - best_bid, midpoint, np.nan) * 10000.0
    microprice = (
        ((best_ask * bid_volumes[0]) + (best_bid * ask_volumes[0])) / l1_total
        if l1_total > 0 and best_bid > 0 and best_ask > 0
        else np.nan
    )
    iep = float(row.get("iep", 0.0) or 0.0)
    microprice_vs_iep_bps = _safe_ratio(microprice - iep, iep, np.nan) * 10000.0
    return {
        "bid_total": bid_total,
        "ask_total": ask_total,
        "bid_ask_imbalance_l1": _safe_ratio(bid_volumes[0] - ask_volumes[0], l1_total),
        "bid_ask_imbalance_l5": _safe_ratio(bid_total - ask_total, bid_total + ask_total),
        "weighted_depth_imbalance": _safe_ratio(
            weighted_bid - weighted_ask,
            weighted_bid + weighted_ask,
        ),
        "spread_bps": float(spread_bps),
        "microprice_vs_iep_bps": float(microprice_vs_iep_bps),
    }


def build_preopen_features(
    snapshots: pd.DataFrame,
    as_of: Any,
    timezone: str = "Asia/Jakarta",
    min_snapshots_per_ticker: int = 6,
    max_snapshot_age_seconds: int = 20,
) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame(columns=["ticker", "as_of", *PREOPEN_FEATURE_COLUMNS])

    as_of_ts = normalize_as_of(as_of, timezone)
    frame = snapshots[snapshots["timestamp"].le(as_of_ts)].copy()
    rows: list[dict[str, Any]] = []
    for ticker, group in frame.groupby("ticker", sort=True):
        group = group.sort_values("timestamp").copy()
        if group.empty:
            continue
        latest = group.iloc[-1]
        first = group.iloc[0]
        previous_close = float(latest["previous_close"])
        iep_values = pd.to_numeric(group["iep"], errors="coerce").to_numpy(dtype=float)
        iev_values = pd.to_numeric(group["iev"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        elapsed_minutes = (
            (group["timestamp"] - group["timestamp"].iloc[0]).dt.total_seconds().to_numpy(dtype=float) / 60.0
        )
        slope = float(np.polyfit(elapsed_minutes, iep_values, 1)[0]) if len(group) >= 2 and elapsed_minutes[-1] > 0 else 0.0
        iep_changes_bps = pd.Series(iep_values).pct_change().replace([np.inf, -np.inf], np.nan).dropna() * 10000.0
        signs = np.sign(iep_values - previous_close)
        signs = signs[signs != 0]
        sign_flips = int(np.sum(signs[1:] != signs[:-1])) if len(signs) > 1 else 0

        depth = _depth_snapshot(latest)
        depth_history: list[dict[str, float]] = []
        if set(DEPTH_COLUMNS).issubset(group.columns):
            depth_history = [_depth_snapshot(row) for _, row in group.iterrows()]
        bid_totals = pd.Series([row["bid_total"] for row in depth_history], dtype=float)
        ask_totals = pd.Series([row["ask_total"] for row in depth_history], dtype=float)
        imbalances = pd.Series([row["bid_ask_imbalance_l5"] for row in depth_history], dtype=float)

        late = group[group["timestamp"].map(lambda ts: ts.timetz().replace(tzinfo=None).strftime("%H:%M:%S") >= "08:56:00")]
        if late.empty:
            late = group.tail(1)
        late_first = late.iloc[0]
        late_iev_max = float(pd.to_numeric(late["iev"], errors="coerce").max() or 0.0)
        avg_daily_volume = float(latest.get("avg_daily_volume_20d", np.nan))
        latest_timestamp = latest["timestamp"]
        latest_age = max(0.0, float((as_of_ts - latest_timestamp).total_seconds()))

        row = {
            "ticker": str(ticker),
            "session_date": latest_timestamp.date().isoformat(),
            "as_of": as_of_ts.isoformat(),
            "latest_timestamp": latest_timestamp.isoformat(),
            "source": str(latest.get("source", "")),
            "rule_version": str(latest.get("rule_version", "")),
            "previous_close": previous_close,
            "latest_iep": float(latest["iep"]),
            "latest_iev": float(latest["iev"]),
            "snapshot_count": int(len(group)),
            "latest_age_seconds": round(latest_age, 3),
            "iep_gap_bps": _safe_ratio(float(latest["iep"]) - previous_close, previous_close) * 10000.0,
            "iep_change_from_first_bps": _safe_ratio(float(latest["iep"]) - float(first["iep"]), previous_close) * 10000.0,
            "iep_slope_bps_per_minute": _safe_ratio(slope, previous_close) * 10000.0,
            "iep_volatility_bps": float(iep_changes_bps.std(ddof=0)) if not iep_changes_bps.empty else 0.0,
            "iep_sign_flips": sign_flips,
            "iep_reversal_from_peak_bps": _safe_ratio(float(latest["iep"]) - float(np.max(iep_values)), previous_close) * 10000.0,
            "iep_rebound_from_trough_bps": _safe_ratio(float(latest["iep"]) - float(np.min(iep_values)), previous_close) * 10000.0,
            "iev_growth_pct": _safe_ratio(float(latest["iev"]) - float(first["iev"]), max(float(first["iev"]), 1.0)) * 100.0,
            "iev_peak_retention": _safe_ratio(float(latest["iev"]), max(float(np.max(iev_values)), 1.0)),
            "iev_to_adv20_pct": _safe_ratio(float(latest["iev"]), avg_daily_volume, np.nan) * 100.0,
            "late_iep_change_bps": _safe_ratio(float(latest["iep"]) - float(late_first["iep"]), previous_close) * 10000.0,
            "late_iev_retention": _safe_ratio(float(latest["iev"]), max(late_iev_max, 1.0)),
            "bid_ask_imbalance_l1": depth["bid_ask_imbalance_l1"],
            "bid_ask_imbalance_l5": depth["bid_ask_imbalance_l5"],
            "weighted_depth_imbalance": depth["weighted_depth_imbalance"],
            "spread_bps": depth["spread_bps"],
            "microprice_vs_iep_bps": depth["microprice_vs_iep_bps"],
            "bid_depth_withdrawal_proxy": _withdrawal_proxy(bid_totals),
            "ask_depth_withdrawal_proxy": _withdrawal_proxy(ask_totals),
            "imbalance_stability": float(1.0 - min(1.0, imbalances.std(ddof=0))) if not imbalances.empty else 0.0,
            "data_ready": bool(len(group) >= max(1, int(min_snapshots_per_ticker)) and latest_age <= max_snapshot_age_seconds),
        }
        rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    numeric_columns = [*PREOPEN_FEATURE_COLUMNS, "previous_close", "latest_iep", "latest_iev"]
    for column in numeric_columns:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out.sort_values(["data_ready", "iep_gap_bps", "ticker"], ascending=[False, False, True]).reset_index(drop=True)