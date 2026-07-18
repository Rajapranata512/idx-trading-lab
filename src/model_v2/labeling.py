"""Leakage-safe trade outcome labels for Model V2 training."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


LABEL_COLUMNS = [
    "y_cls",
    "y_reg",
    "outcome",
    "entry_price",
    "entry_eligible",
    "entry_gap_pct",
    "exit_price",
    "exit_date",
    "holding_days",
    "ambiguous_intrabar",
    "gap_exit",
    "mae_r",
    "mfe_r",
    "net_return_pct",
]


def _empty_labeled_frame(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    text_columns = {"outcome", "exit_date"}
    bool_columns = {"entry_eligible", "ambiguous_intrabar", "gap_exit"}
    for column in LABEL_COLUMNS:
        if column in text_columns:
            out[column] = pd.Series(dtype=str)
        elif column in bool_columns:
            out[column] = pd.Series(dtype=bool)
        else:
            out[column] = pd.Series(dtype=float)
    return out


def simulate_trade_outcomes(
    bars: pd.DataFrame,
    mode: str,
    horizon_days: int,
    stop_atr_mult: float = 2.0,
    tp1_r_mult: float = 1.0,
    roundtrip_cost_pct: float = 0.65,
    horizon_exit_min_r: float = 0.0,
) -> pd.DataFrame:
    """Simulate stop/TP first-touch outcomes on future OHLC bars.

    The signal-bar close defines the planned stop/TP geometry, while execution
    occurs at the next session open. An entry is rejected when that open has
    already crossed the planned stop or TP. Later gaps through a barrier exit at
    the open. Ambiguous bars use a conservative stop-first policy.
    """
    del mode  # The geometry is mode-independent; mode controls the horizon.
    if bars.empty:
        return _empty_labeled_frame(bars)

    required = {"date", "ticker", "open", "high", "low", "close"}
    missing = sorted(required - set(bars.columns))
    if missing:
        raise ValueError(f"Missing outcome columns: {', '.join(missing)}")

    df = bars.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker", "close"]).copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    if "atr_14" not in df.columns:
        df["atr_14"] = df.groupby("ticker")["close"].transform(
            lambda series: series.rolling(14).std() * np.sqrt(14)
        )

    df["_bar_idx"] = range(len(df))
    ticker_groups = df.groupby("ticker")["_bar_idx"].apply(list).to_dict()
    cost_fraction = max(0.0, float(roundtrip_cost_pct)) / 100.0
    horizon = max(1, int(horizon_days))
    results: list[dict[str, Any]] = []

    for idxs in ticker_groups.values():
        idxs_array = np.asarray(idxs, dtype=int)
        bar_count = len(idxs_array)
        for position, bar_index in enumerate(idxs_array):
            row = df.iloc[bar_index]
            planned_entry = float(row["close"])
            atr_value = float(row.get("atr_14", 0.0))
            if not np.isfinite(atr_value) or atr_value <= 0 or planned_entry <= 0:
                continue

            planned_risk = atr_value * float(stop_atr_mult)
            if planned_risk <= 0:
                continue
            stop_price = planned_entry - planned_risk
            tp_price = planned_entry + (planned_risk * float(tp1_r_mult))
            forward_end = min(position + 1 + horizon, bar_count)
            forward_indices = idxs_array[position + 1 : forward_end]
            if len(forward_indices) == 0:
                continue

            entry_bar = df.iloc[forward_indices[0]]
            entry_price = float(entry_bar["open"])
            entry_gap_pct = ((entry_price - planned_entry) / planned_entry) * 100.0
            if entry_price <= stop_price or entry_price >= tp_price:
                results.append(
                    {
                        "_bar_idx": int(bar_index),
                        "y_cls": np.nan,
                        "y_reg": np.nan,
                        "outcome": "entry_rejected_gap",
                        "entry_price": round(entry_price, 4),
                        "entry_eligible": False,
                        "entry_gap_pct": round(float(entry_gap_pct), 6),
                        "exit_price": np.nan,
                        "exit_date": "",
                        "holding_days": 0,
                        "ambiguous_intrabar": False,
                        "gap_exit": False,
                        "mae_r": np.nan,
                        "mfe_r": np.nan,
                        "net_return_pct": np.nan,
                    }
                )
                continue

            risk_per_share = max(entry_price - stop_price, entry_price * 0.005)

            outcome = "horizon_exit"
            exit_price = entry_price
            exit_date = pd.NaT
            holding_days = 0
            ambiguous_intrabar = False
            gap_exit = False
            path_low = entry_price
            path_high = entry_price

            for day_number, forward_index in enumerate(forward_indices, start=1):
                forward = df.iloc[forward_index]
                open_price = float(forward["open"])
                low_price = float(forward["low"])
                high_price = float(forward["high"])
                close_price = float(forward["close"])
                path_low = min(path_low, low_price)
                path_high = max(path_high, high_price)
                exit_price = close_price
                exit_date = forward["date"]
                holding_days = day_number

                if day_number > 1 and open_price <= stop_price:
                    outcome = "stop_hit"
                    exit_price = open_price
                    gap_exit = True
                    break
                if day_number > 1 and open_price >= tp_price:
                    outcome = "tp_hit"
                    exit_price = open_price
                    gap_exit = True
                    break

                stop_hit = low_price <= stop_price
                tp_hit = high_price >= tp_price
                if stop_hit and tp_hit:
                    outcome = "stop_hit"
                    exit_price = stop_price
                    ambiguous_intrabar = True
                    break
                if stop_hit:
                    outcome = "stop_hit"
                    exit_price = stop_price
                    break
                if tp_hit:
                    outcome = "tp_hit"
                    exit_price = tp_price
                    break

            gross_r = (exit_price - entry_price) / risk_per_share
            cost_r = cost_fraction * entry_price / risk_per_share
            net_r = gross_r - cost_r
            net_return = ((exit_price - entry_price) / entry_price) - cost_fraction
            positive_horizon_exit = outcome == "horizon_exit" and net_r > float(horizon_exit_min_r)
            y_cls = int(outcome == "tp_hit" or positive_horizon_exit)

            results.append(
                {
                    "_bar_idx": int(bar_index),
                    "y_cls": y_cls,
                    "y_reg": round(float(net_r), 6),
                    "outcome": outcome,
                    "entry_price": round(float(entry_price), 4),
                    "entry_eligible": True,
                    "entry_gap_pct": round(float(entry_gap_pct), 6),
                    "exit_price": round(float(exit_price), 4),
                    "exit_date": pd.Timestamp(exit_date).date().isoformat() if pd.notna(exit_date) else "",
                    "holding_days": int(holding_days),
                    "ambiguous_intrabar": bool(ambiguous_intrabar),
                    "gap_exit": bool(gap_exit),
                    "mae_r": round(float((path_low - entry_price) / risk_per_share), 6),
                    "mfe_r": round(float((path_high - entry_price) / risk_per_share), 6),
                    "net_return_pct": round(float(net_return * 100.0), 6),
                }
            )

    if not results:
        out = _empty_labeled_frame(df)
        out.drop(columns=["_bar_idx"], inplace=True, errors="ignore")
        return out

    result_df = pd.DataFrame(results)
    out = df.merge(result_df, on="_bar_idx", how="left")
    out.drop(columns=["_bar_idx"], inplace=True, errors="ignore")
    return out


def _align_to_live_candidates(
    mode_df: pd.DataFrame,
    min_live_score: float,
    top_n_per_date: int,
) -> pd.DataFrame:
    if "score" not in mode_df.columns:
        raise ValueError("Candidate-aligned training requires score")
    ranked = mode_df.copy()
    ranked["score"] = pd.to_numeric(ranked["score"], errors="coerce")
    ranked = ranked.dropna(subset=["score"]).sort_values(
        ["date", "score", "ticker"],
        ascending=[True, False, True],
    )
    ranked["candidate_rank"] = ranked.groupby("date").cumcount() + 1
    ranked["candidate_aligned"] = True
    ranked["candidate_score_floor"] = float(min_live_score)
    ranked["candidate_top_n"] = int(top_n_per_date)
    return ranked[
        ranked["score"].ge(float(min_live_score))
        & ranked["candidate_rank"].le(max(1, int(top_n_per_date)))
    ].copy()


def build_training_dataset(
    scored_history: pd.DataFrame,
    mode: str,
    horizon_days: int,
    stop_atr_mult: float = 2.0,
    tp1_r_mult: float = 1.0,
    roundtrip_cost_pct: float = 0.65,
    train_lookback_days: int = 0,
    candidate_alignment_enabled: bool = False,
    min_live_score: float = 0.0,
    top_n_per_date: int = 10,
    horizon_exit_min_r: float = 0.0,
) -> pd.DataFrame:
    """Build outcome labels, optionally restricted to the V1 live candidate set."""
    if scored_history.empty:
        return pd.DataFrame()

    mode_key = str(mode).strip().lower()
    df = scored_history.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["mode"] = df.get("mode", "").astype(str).str.lower().str.strip()
    df = df.dropna(subset=["date", "ticker", "close"]).copy()
    mode_df = df[df["mode"].eq(mode_key)].copy()
    if mode_df.empty:
        return pd.DataFrame()

    if train_lookback_days > 0:
        max_date = mode_df["date"].max()
        if pd.notna(max_date):
            cutoff = pd.Timestamp(max_date) - pd.Timedelta(days=int(train_lookback_days))
            mode_df = mode_df[mode_df["date"] >= cutoff].copy()
    if mode_df.empty:
        return pd.DataFrame()

    candidate_pool_rows = int(len(mode_df))
    if candidate_alignment_enabled:
        mode_df = _align_to_live_candidates(
            mode_df,
            min_live_score=min_live_score,
            top_n_per_date=top_n_per_date,
        )
    else:
        mode_df["candidate_aligned"] = False
        mode_df["candidate_rank"] = pd.to_numeric(mode_df.get("rank"), errors="coerce")
        mode_df["candidate_score_floor"] = float(min_live_score)
        mode_df["candidate_top_n"] = int(top_n_per_date)
    if mode_df.empty:
        return pd.DataFrame()

    tickers = mode_df["ticker"].unique()
    all_bars = df[df["ticker"].isin(tickers)].copy()
    all_bars = all_bars.drop_duplicates(subset=["ticker", "date"], keep="first")
    all_bars = all_bars.sort_values(["ticker", "date"]).reset_index(drop=True)
    labeled_bars = simulate_trade_outcomes(
        bars=all_bars,
        mode=mode_key,
        horizon_days=horizon_days,
        stop_atr_mult=stop_atr_mult,
        tp1_r_mult=tp1_r_mult,
        roundtrip_cost_pct=roundtrip_cost_pct,
        horizon_exit_min_r=horizon_exit_min_r,
    )

    label_columns = ["ticker", "date", *LABEL_COLUMNS]
    labels = labeled_bars[
        [column for column in label_columns if column in labeled_bars.columns]
    ].drop_duplicates(subset=["ticker", "date"], keep="first")
    out = mode_df.merge(labels, on=["ticker", "date"], how="left")
    selected_candidate_rows = int(len(out))
    entry_rejected_rows = int(out.get("outcome", "").eq("entry_rejected_gap").sum())
    out = out.dropna(subset=["y_cls"]).copy()
    out["y"] = pd.to_numeric(out["y_cls"], errors="coerce").astype(int)
    out["net_return"] = pd.to_numeric(out["y_reg"], errors="coerce").astype(float)
    out["label_strategy"] = "first_touch_stop_tp_with_net_horizon_exit"
    out["candidate_pool_rows"] = candidate_pool_rows
    out["selected_candidate_rows"] = selected_candidate_rows
    out["entry_rejected_rows"] = entry_rejected_rows
    return out
