"""Labeling V2 — realistic trade outcome simulation for model training.

Simulates intrabar stop-loss / take-profit hits using OHLC data within the
holding horizon, producing labels that match live execution behaviour.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _compute_stop_tp(
    entry_close: pd.Series,
    atr: pd.Series,
    stop_atr_mult: float,
    tp1_r_mult: float,
) -> tuple[pd.Series, pd.Series]:
    """Derive stop and TP1 prices from entry close and ATR."""
    risk = atr * stop_atr_mult
    stop = entry_close - risk
    tp1 = entry_close + risk * tp1_r_mult
    return stop.astype(float), tp1.astype(float)


def simulate_trade_outcomes(
    bars: pd.DataFrame,
    mode: str,
    horizon_days: int,
    stop_atr_mult: float = 2.0,
    tp1_r_mult: float = 1.0,
    roundtrip_cost_pct: float = 0.65,
) -> pd.DataFrame:
    """Simulate realistic trade outcomes with intrabar stop/TP checking.

    For each entry bar, walks forward up to *horizon_days* and checks whether
    the low hits the stop or the high hits the TP first.  When the stop is hit
    on the same bar as the TP (ambiguous), we conservatively call it a loss
    (stop hit assumed first via intrabar ordering: open → low → high → close).

    Parameters
    ----------
    bars : DataFrame
        Must contain: date, ticker, open, high, low, close, volume, atr_14.
        Should be pre-sorted by (ticker, date).
    mode : str
        Trading mode identifier (``"t1"`` or ``"swing"``).
    horizon_days : int
        Maximum holding period in trading days.
    stop_atr_mult : float
        Stop distance = entry_close − ATR × stop_atr_mult.
    tp1_r_mult : float
        TP1 distance = entry_close + risk × tp1_r_mult.
    roundtrip_cost_pct : float
        Total round-trip cost (buy fee + sell fee + 2 × slippage) in percent.

    Returns
    -------
    DataFrame with original columns plus:
        y_cls   : 1 if TP1 was hit before stop (or horizon exit > entry), else 0
        y_reg   : realized R-multiple (net of costs)
        outcome : "tp_hit" | "stop_hit" | "horizon_exit"
        exit_price : price at which the trade was closed
    """
    if bars.empty:
        out = bars.copy()
        for c in ["y_cls", "y_reg", "outcome", "exit_price"]:
            out[c] = pd.Series(dtype=float if c != "outcome" else str)
        return out

    df = bars.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker", "close"]).copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Ensure ATR is available (needed for stop/TP)
    if "atr_14" not in df.columns:
        df["atr_14"] = df.groupby("ticker")["close"].transform(
            lambda s: s.rolling(14).std() * np.sqrt(14)
        )

    # Build unique (ticker, date) bar index for fast lookup
    df["_bar_idx"] = range(len(df))
    ticker_groups = df.groupby("ticker")["_bar_idx"].apply(list).to_dict()

    results: list[dict[str, Any]] = []

    cost_mult = roundtrip_cost_pct / 100.0

    for ticker, idxs in ticker_groups.items():
        idxs_arr = np.array(idxs)
        n = len(idxs_arr)

        for pos, bar_i in enumerate(idxs_arr):
            row = df.iloc[bar_i]
            entry_close = float(row["close"])
            atr_val = float(row.get("atr_14", 0.0))

            # Skip if ATR is missing/zero (cannot compute stop)
            if np.isnan(atr_val) or atr_val <= 0:
                continue

            risk = atr_val * stop_atr_mult
            stop_price = entry_close - risk
            tp_price = entry_close + risk * tp1_r_mult

            # Walk forward bars
            max_fwd = min(pos + 1 + horizon_days, n)
            fwd_range = idxs_arr[pos + 1 : max_fwd]

            if len(fwd_range) == 0:
                continue  # no forward data

            outcome = "horizon_exit"
            exit_price = entry_close  # fallback

            for fwd_i in fwd_range:
                fwd_row = df.iloc[fwd_i]
                fwd_low = float(fwd_row["low"])
                fwd_high = float(fwd_row["high"])
                fwd_close = float(fwd_row["close"])

                stop_hit = fwd_low <= stop_price
                tp_hit = fwd_high >= tp_price

                if stop_hit and tp_hit:
                    # Ambiguous — conservatively assume stop hit first
                    outcome = "stop_hit"
                    exit_price = stop_price
                    break
                elif stop_hit:
                    outcome = "stop_hit"
                    exit_price = stop_price
                    break
                elif tp_hit:
                    outcome = "tp_hit"
                    exit_price = tp_price
                    break
                else:
                    exit_price = fwd_close  # horizon exit uses last close

            # Compute R-multiple
            if risk > 0:
                gross_r = (exit_price - entry_close) / risk
            else:
                gross_r = 0.0

            net_return = (exit_price - entry_close) / (entry_close + 1e-9) - cost_mult
            net_r = gross_r - (cost_mult * entry_close / (risk + 1e-9))

            y_cls = 1 if outcome == "tp_hit" else (1 if (outcome == "horizon_exit" and net_return > 0) else 0)

            results.append({
                "_bar_idx": bar_i,
                "y_cls": int(y_cls),
                "y_reg": round(float(net_r), 6),
                "outcome": outcome,
                "exit_price": round(float(exit_price), 2),
            })

    if not results:
        out = df.copy()
        for c in ["y_cls", "y_reg", "outcome", "exit_price"]:
            out[c] = pd.Series(dtype=float if c != "outcome" else str)
        out.drop(columns=["_bar_idx"], inplace=True, errors="ignore")
        return out

    result_df = pd.DataFrame(results)
    out = df.merge(result_df, on="_bar_idx", how="left")
    out.drop(columns=["_bar_idx"], inplace=True, errors="ignore")
    return out


def build_training_dataset(
    scored_history: pd.DataFrame,
    mode: str,
    horizon_days: int,
    stop_atr_mult: float = 2.0,
    tp1_r_mult: float = 1.0,
    roundtrip_cost_pct: float = 0.65,
    train_lookback_days: int = 0,
) -> pd.DataFrame:
    """Prepare labeled training dataset for a given mode.

    Filters scored_history to the requested mode, applies the stop/TP
    simulation, and returns rows with valid labels ready for model training.
    """
    if scored_history.empty:
        return pd.DataFrame()

    df = scored_history.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker", "mode", "close"]).copy()

    if df.empty:
        return pd.DataFrame()

    # Filter to mode
    mode_df = df[df["mode"] == mode].copy()
    if mode_df.empty:
        return pd.DataFrame()

    # Apply lookback window
    if train_lookback_days > 0:
        max_date = mode_df["date"].max()
        if pd.notna(max_date):
            cutoff = pd.Timestamp(max_date) - pd.Timedelta(days=int(train_lookback_days))
            mode_df = mode_df[mode_df["date"] >= cutoff].copy()

    if mode_df.empty:
        return pd.DataFrame()

    # We need OHLC + atr for ALL tickers (not just mode-filtered) to walk forward
    # Get the unique tickers+dates from mode_df, then get full bar data
    tickers = mode_df["ticker"].unique()
    all_bars = df[df["ticker"].isin(tickers)].copy()
    all_bars = all_bars.drop_duplicates(subset=["ticker", "date"], keep="first")
    all_bars = all_bars.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Run simulation on the full bar data
    labeled_bars = simulate_trade_outcomes(
        bars=all_bars,
        mode=mode,
        horizon_days=horizon_days,
        stop_atr_mult=stop_atr_mult,
        tp1_r_mult=tp1_r_mult,
        roundtrip_cost_pct=roundtrip_cost_pct,
    )

    # Merge labels back to mode_df (which has the features/scores)
    label_cols = ["ticker", "date", "y_cls", "y_reg", "outcome", "exit_price"]
    available = [c for c in label_cols if c in labeled_bars.columns]
    labels = labeled_bars[available].drop_duplicates(subset=["ticker", "date"], keep="first")

    out = mode_df.merge(labels, on=["ticker", "date"], how="left")
    out = out.dropna(subset=["y_cls"]).copy()
    out["y"] = out["y_cls"].astype(int)
    out["net_return"] = out["y_reg"].astype(float)

    return out
