from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings
from src.strategy import score_history_modes
from src.utils import atomic_write_json


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except Exception:
        return default


def _round(value: Any, digits: int = 4, default: float = 0.0) -> float:
    return round(_safe_float(value, default=default), digits)


def _profit_factor(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    gross_profit = float(clean[clean > 0].sum())
    gross_loss = float(-clean[clean < 0].sum())
    if gross_loss <= 0:
        return 999.0 if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _threshold_for_mode(settings: Settings, mode: str) -> float:
    if mode == "t1":
        return float(settings.pipeline.min_live_score_t1)
    if mode == "swing":
        return float(settings.pipeline.min_live_score_swing)
    return 0.0


def _horizon_for_mode(settings: Settings, mode: str) -> int:
    if mode == "t1":
        return int(settings.model_v2.horizon_days_t1)
    if mode == "swing":
        return int(settings.model_v2.horizon_days_swing)
    return 1


def _liquidity_bucket(avg_vol_20d: Any, settings: Settings) -> str:
    avg_vol = _safe_float(avg_vol_20d)
    if avg_vol >= float(settings.backtest.liq_bucket_high_avg_volume_20d):
        return "high"
    if avg_vol >= float(settings.backtest.liq_bucket_mid_avg_volume_20d):
        return "mid"
    return "low"


def _volatility_bucket(series: pd.Series) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce")
    if clean.dropna().empty:
        return pd.Series("unknown", index=series.index, dtype=str)
    if clean.notna().sum() < 3 or clean.nunique(dropna=True) < 3:
        median = clean.median()
        return clean.apply(lambda value: "unknown" if pd.isna(value) else ("high" if value >= median else "low"))
    try:
        return pd.qcut(clean, q=3, labels=["low", "mid", "high"], duplicates="drop").astype(str)
    except Exception:
        median = clean.median()
        return clean.apply(lambda value: "unknown" if pd.isna(value) else ("high" if value >= median else "low"))


def _score_bucket(score: Any, edges: list[float]) -> str:
    value = _safe_float(score, default=-1.0)
    clean_edges = sorted({float(edge) for edge in edges})
    if len(clean_edges) < 2:
        clean_edges = [0.0, 60.0, 70.0, 80.0, 90.0, 95.0, 100.0]
    if value < clean_edges[0]:
        return f"<{clean_edges[0]:g}"
    for left, right in zip(clean_edges[:-1], clean_edges[1:]):
        if left <= value <= right:
            return f"{left:g}-{right:g}"
    return f">={clean_edges[-1]:g}"


def _daily_regime_table(features: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    df = features.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "regime_status"])

    rows: list[dict[str, Any]] = []
    for date_value, grp in df.groupby("date", dropna=False):
        ma50_valid = grp.dropna(subset=["close", "ma_50"]) if {"close", "ma_50"} <= set(grp.columns) else pd.DataFrame()
        ma20_valid = grp.dropna(subset=["close", "ma_20"]) if {"close", "ma_20"} <= set(grp.columns) else pd.DataFrame()
        ret20_valid = grp.dropna(subset=["ret_20d"]) if "ret_20d" in grp.columns else pd.DataFrame()
        atr_valid = grp.dropna(subset=["atr_pct"]) if "atr_pct" in grp.columns else pd.DataFrame()

        breadth_ma50_pct = float((ma50_valid["close"] > ma50_valid["ma_50"]).mean() * 100.0) if len(ma50_valid) else 0.0
        breadth_ma20_pct = float((ma20_valid["close"] > ma20_valid["ma_20"]).mean() * 100.0) if len(ma20_valid) else 0.0
        avg_ret20_pct = float(ret20_valid["ret_20d"].mean() * 100.0) if len(ret20_valid) else 0.0
        median_atr_pct = float(atr_valid["atr_pct"].median()) if len(atr_valid) else 0.0
        checks = [
            breadth_ma50_pct >= float(settings.regime.min_breadth_ma50_pct),
            breadth_ma20_pct >= float(settings.regime.min_breadth_ma20_pct),
            avg_ret20_pct >= float(settings.regime.min_avg_ret20_pct),
            median_atr_pct <= float(settings.regime.max_median_atr_pct),
        ]
        rows.append(
            {
                "date": pd.Timestamp(date_value).strftime("%Y-%m-%d"),
                "regime_status": "risk_on" if all(checks) else "risk_off",
                "breadth_ma50_pct": round(breadth_ma50_pct, 4),
                "breadth_ma20_pct": round(breadth_ma20_pct, 4),
                "avg_ret20_pct": round(avg_ret20_pct, 4),
                "median_atr_pct": round(median_atr_pct, 4),
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def _candidate_signals(features: pd.DataFrame, settings: Settings, max_rank: int) -> pd.DataFrame:
    scored = score_history_modes(features, min_avg_volume_20d=settings.pipeline.min_avg_volume_20d)
    if scored.empty:
        return scored
    scored = scored.copy()
    scored["date"] = pd.to_datetime(scored["date"], errors="coerce")
    scored["ticker"] = scored["ticker"].astype(str).str.upper().str.strip()
    scored["mode"] = scored["mode"].astype(str).str.lower().str.strip()
    scored["score"] = pd.to_numeric(scored["score"], errors="coerce")
    active_modes = {str(mode).lower().strip() for mode in settings.pipeline.active_modes}
    scored = scored[scored["mode"].isin(active_modes)].dropna(subset=["date", "ticker", "close", "score"]).copy()
    if scored.empty:
        return scored
    scored = scored.sort_values(["date", "mode", "score"], ascending=[True, True, False]).copy()
    scored["rank"] = scored.groupby(["date", "mode"]).cumcount() + 1
    scored = scored[scored["rank"] <= max_rank].copy()
    scored["passes_live_threshold"] = scored.apply(
        lambda row: float(row["score"]) >= _threshold_for_mode(settings, str(row["mode"])),
        axis=1,
    )
    return scored.reset_index(drop=True)


def _bar_lookup(features: pd.DataFrame) -> dict[str, pd.DataFrame]:
    bars = features.copy()
    bars["date"] = pd.to_datetime(bars["date"], errors="coerce")
    required = ["date", "ticker", "open", "high", "low", "close"]
    bars = bars.dropna(subset=[col for col in required if col in bars.columns]).copy()
    bars["ticker"] = bars["ticker"].astype(str).str.upper().str.strip()
    bars = bars.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="first")
    return {ticker: grp.reset_index(drop=True) for ticker, grp in bars.groupby("ticker", dropna=False)}


def _risk_geometry(signal: pd.Series, settings: Settings) -> dict[str, float]:
    entry = _safe_float(signal.get("close"))
    atr = _safe_float(signal.get("atr_14"))
    if atr <= 0:
        atr_pct = _safe_float(signal.get("atr_pct"))
        atr = entry * (atr_pct / 100.0) if atr_pct > 0 else entry * 0.02
    risk_per_share = max(float(settings.risk.stop_atr_multiple) * atr, entry * 0.005, 1e-9)
    stop = entry - risk_per_share
    tp1 = entry + (float(settings.risk.tp1_r_multiple) * risk_per_share)
    tp2 = entry + (float(settings.risk.tp2_r_multiple) * risk_per_share)
    return {
        "entry": entry,
        "atr": atr,
        "risk_per_share": risk_per_share,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
    }


def _net_r(entry: float, exit_price: float, risk_per_share: float, settings: Settings) -> float:
    buy_cost = (float(settings.backtest.buy_fee_pct) + float(settings.backtest.slippage_pct)) / 100.0
    sell_cost = (float(settings.backtest.sell_fee_pct) + float(settings.backtest.slippage_pct)) / 100.0
    entry_exec = entry * (1.0 + buy_cost)
    exit_exec = exit_price * (1.0 - sell_cost)
    return (exit_exec - entry_exec) / max(risk_per_share, 1e-9)


def _simulate_signal(
    signal: pd.Series,
    bars_by_ticker: dict[str, pd.DataFrame],
    settings: Settings,
) -> dict[str, Any] | None:
    ticker = str(signal.get("ticker", "")).upper().strip()
    mode = str(signal.get("mode", "")).lower().strip()
    ticker_bars = bars_by_ticker.get(ticker)
    if ticker_bars is None or ticker_bars.empty:
        return None
    signal_date = pd.Timestamp(signal.get("date"))
    matches = ticker_bars.index[ticker_bars["date"] == signal_date].tolist()
    if not matches:
        return None
    idx = int(matches[0])
    horizon = max(1, _horizon_for_mode(settings, mode))
    if idx + horizon >= len(ticker_bars):
        return None

    geom = _risk_geometry(signal, settings)
    entry = geom["entry"]
    risk_per_share = geom["risk_per_share"]
    if entry <= 0 or risk_per_share <= 0:
        return None

    future = ticker_bars.iloc[idx + 1 : idx + horizon + 1].copy()
    if len(future) < horizon:
        return None

    tp1_touched = False
    tp2_touched = False
    outcome = "horizon_exit"
    exit_price = _safe_float(future.iloc[-1].get("close"))
    exit_date = pd.Timestamp(future.iloc[-1]["date"])
    bars_to_exit = horizon
    min_low = entry
    max_high = entry

    for offset, (_, bar) in enumerate(future.iterrows(), start=1):
        high = _safe_float(bar.get("high"))
        low = _safe_float(bar.get("low"))
        close = _safe_float(bar.get("close"))
        if high > 0:
            max_high = max(max_high, high)
        if low > 0:
            min_low = min(min_low, low)

        if not tp1_touched:
            stop_hit = low > 0 and low <= geom["stop"]
            tp2_hit = high > 0 and high >= geom["tp2"]
            tp1_hit = high > 0 and high >= geom["tp1"]
            if stop_hit:
                outcome = "stop_loss"
                exit_price = geom["stop"]
                exit_date = pd.Timestamp(bar["date"])
                bars_to_exit = offset
                break
            if tp2_hit:
                tp1_touched = True
                tp2_touched = True
                outcome = "tp2_hit"
                exit_price = geom["tp2"]
                exit_date = pd.Timestamp(bar["date"])
                bars_to_exit = offset
                break
            if tp1_hit:
                tp1_touched = True
                continue
        else:
            breakeven_hit = low > 0 and low <= entry
            tp2_hit = high > 0 and high >= geom["tp2"]
            if breakeven_hit:
                outcome = "breakeven_stop"
                exit_price = entry
                exit_date = pd.Timestamp(bar["date"])
                bars_to_exit = offset
                break
            if tp2_hit:
                tp2_touched = True
                outcome = "tp2_hit"
                exit_price = geom["tp2"]
                exit_date = pd.Timestamp(bar["date"])
                bars_to_exit = offset
                break
        if offset == horizon:
            exit_price = close

    realized_r = _net_r(entry, exit_price, risk_per_share, settings)
    return_pct = (realized_r * risk_per_share / max(entry, 1e-9)) * 100.0
    decay: dict[str, float | None] = {}
    for day in sorted({int(day) for day in settings.signal_accuracy.decay_days if int(day) > 0}):
        if idx + day < len(ticker_bars):
            decay_close = _safe_float(ticker_bars.iloc[idx + day].get("close"))
            decay[f"decay_{day}d_r"] = _net_r(entry, decay_close, risk_per_share, settings) if decay_close > 0 else None
        else:
            decay[f"decay_{day}d_r"] = None

    raw_p_win = signal.get("shadow_p_win", None)
    p_source = "shadow_p_win"
    p_win = _safe_float(raw_p_win, default=-1.0)
    if p_win < 0 or p_win > 1:
        p_win = max(0.0, min(1.0, _safe_float(signal.get("score")) / 100.0))
        p_source = "score_scaled"

    row = {
        "date": signal_date.strftime("%Y-%m-%d"),
        "exit_date": exit_date.strftime("%Y-%m-%d"),
        "ticker": ticker,
        "mode": mode,
        "rank": int(signal.get("rank", 0)),
        "score": _round(signal.get("score"), 4),
        "predicted_p_win": round(p_win, 6),
        "predicted_p_win_source": p_source,
        "passes_live_threshold": bool(signal.get("passes_live_threshold", False)),
        "horizon_days": horizon,
        "bars_to_exit": int(bars_to_exit),
        "entry": _round(entry, 4),
        "stop": _round(geom["stop"], 4),
        "tp1": _round(geom["tp1"], 4),
        "tp2": _round(geom["tp2"], 4),
        "exit_price": _round(exit_price, 4),
        "outcome": outcome,
        "win": bool(realized_r > 0),
        "tp1_touched": bool(tp1_touched),
        "tp2_touched": bool(tp2_touched),
        "realized_r": round(realized_r, 6),
        "return_pct": round(return_pct, 6),
        "mae_r": round((min_low - entry) / risk_per_share, 6),
        "mfe_r": round((max_high - entry) / risk_per_share, 6),
        "atr_pct": _round(signal.get("atr_pct"), 4),
        "avg_vol_20d": _round(signal.get("avg_vol_20d"), 2),
        "ret_20d_pct": round(_safe_float(signal.get("ret_20d")) * 100.0, 4),
        "liquidity_bucket": _liquidity_bucket(signal.get("avg_vol_20d"), settings),
        "score_bucket": _score_bucket(signal.get("score"), settings.signal_accuracy.score_bucket_edges),
    }
    row.update({key: None if value is None else round(float(value), 6) for key, value in decay.items()})
    return row


def _build_audit_trades(features: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    max_rank = max([int(k) for k in settings.signal_accuracy.precision_top_k] + [int(settings.signal_accuracy.max_signals_per_day), 1])
    candidates = _candidate_signals(features, settings, max_rank=max_rank)
    if candidates.empty:
        return pd.DataFrame()

    bars_by_ticker = _bar_lookup(features)
    rows: list[dict[str, Any]] = []
    for _, signal in candidates.iterrows():
        outcome = _simulate_signal(signal, bars_by_ticker=bars_by_ticker, settings=settings)
        if outcome is not None:
            rows.append(outcome)
    trades = pd.DataFrame(rows)
    if trades.empty:
        return trades

    regime = _daily_regime_table(features, settings)
    if not regime.empty:
        trades = trades.merge(regime[["date", "regime_status"]], on="date", how="left")
    trades["regime_status"] = trades.get("regime_status", pd.Series(index=trades.index, dtype=str)).fillna("unknown")
    trades["volatility_bucket"] = _volatility_bucket(trades["atr_pct"]).astype(str)
    return trades


def _summarize_trades(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "trade_count": 0,
            "precision_pct": 0.0,
            "expectancy_r": 0.0,
            "profit_factor_r": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "avg_mae_r": 0.0,
            "worst_mae_r": 0.0,
            "avg_mfe_r": 0.0,
        }
    realized = pd.to_numeric(df["realized_r"], errors="coerce").dropna()
    wins = realized[realized > 0]
    losses = realized[realized < 0]
    return {
        "trade_count": int(len(realized)),
        "precision_pct": round(float((realized > 0).mean() * 100.0), 2) if not realized.empty else 0.0,
        "expectancy_r": round(float(realized.mean()), 4) if not realized.empty else 0.0,
        "profit_factor_r": round(float(_profit_factor(realized)), 4) if not realized.empty else 0.0,
        "avg_win_r": round(float(wins.mean()), 4) if not wins.empty else 0.0,
        "avg_loss_r": round(float(losses.mean()), 4) if not losses.empty else 0.0,
        "avg_mae_r": round(float(pd.to_numeric(df["mae_r"], errors="coerce").mean()), 4),
        "worst_mae_r": round(float(pd.to_numeric(df["mae_r"], errors="coerce").min()), 4),
        "avg_mfe_r": round(float(pd.to_numeric(df["mfe_r"], errors="coerce").mean()), 4),
        "median_score": round(float(pd.to_numeric(df["score"], errors="coerce").median()), 4),
        "tp1_touch_rate_pct": round(float(pd.to_numeric(df["tp1_touched"], errors="coerce").mean() * 100.0), 2),
        "tp2_hit_rate_pct": round(float(pd.to_numeric(df["tp2_touched"], errors="coerce").mean() * 100.0), 2),
        "stop_rate_pct": round(float((df["outcome"] == "stop_loss").mean() * 100.0), 2),
        "breakeven_rate_pct": round(float((df["outcome"] == "breakeven_stop").mean() * 100.0), 2),
    }


def _summarize_group(df: pd.DataFrame, group_cols: list[str], min_live_only: bool = False) -> pd.DataFrame:
    columns = [*group_cols, "trade_count", "precision_pct", "expectancy_r", "profit_factor_r", "avg_win_r", "avg_loss_r", "avg_mae_r", "worst_mae_r", "avg_mfe_r", "median_score", "tp1_touch_rate_pct", "tp2_hit_rate_pct", "stop_rate_pct", "live_trade_count", "live_expectancy_r", "live_profit_factor_r"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    source = df[df["passes_live_threshold"]].copy() if min_live_only else df.copy()
    if source.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for key, grp in source.groupby(group_cols, dropna=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        row = {col: str(value) for col, value in zip(group_cols, key_tuple)}
        row.update(_summarize_trades(grp))
        live_grp = grp[grp["passes_live_threshold"]].copy()
        live_summary = _summarize_trades(live_grp)
        row["live_trade_count"] = live_summary["trade_count"]
        row["live_expectancy_r"] = live_summary["expectancy_r"]
        row["live_profit_factor_r"] = live_summary["profit_factor_r"]
        rows.append(row)
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["expectancy_r", "profit_factor_r", "trade_count"], ascending=[True, True, False]).reset_index(drop=True)
    return out


def _records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    source = df.head(limit).copy() if limit is not None else df.copy()
    records: list[dict[str, Any]] = []
    for record in source.to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for key, value in record.items():
            if pd.isna(value):
                clean[key] = None
            elif isinstance(value, (pd.Timestamp,)):
                clean[key] = value.strftime("%Y-%m-%d")
            else:
                clean[key] = value
        records.append(clean)
    return records


def _precision_at_k(df: pd.DataFrame, k: int, mode: str | None = None) -> dict[str, Any]:
    source = df.copy()
    if mode is not None:
        source = source[source["mode"] == mode].copy()
    if source.empty:
        return {"k": int(k), "sample_count": 0, "precision_pct": 0.0, "expectancy_r": 0.0}
    source = source.sort_values(["date", "score"], ascending=[True, False]).copy()
    top = source.groupby("date").head(int(k)).copy()
    summary = _summarize_trades(top)
    return {
        "k": int(k),
        "sample_count": int(summary["trade_count"]),
        "precision_pct": float(summary["precision_pct"]),
        "expectancy_r": float(summary["expectancy_r"]),
        "profit_factor_r": float(summary["profit_factor_r"]),
    }


def _calibration_summary(df: pd.DataFrame, bins: int) -> dict[str, Any]:
    if df.empty:
        return {"status": "no_trades", "source": "", "ece": 0.0, "bins": []}
    source = df.dropna(subset=["predicted_p_win", "win"]).copy()
    if source.empty:
        return {"status": "no_probability", "source": "", "ece": 0.0, "bins": []}
    source["predicted_p_win"] = pd.to_numeric(source["predicted_p_win"], errors="coerce").clip(0.0, 1.0)
    source = source.dropna(subset=["predicted_p_win"]).copy()
    if source.empty:
        return {"status": "no_probability", "source": "", "ece": 0.0, "bins": []}
    bin_count = max(2, int(bins))
    edges = [i / bin_count for i in range(bin_count + 1)]
    source["calibration_bin"] = pd.cut(source["predicted_p_win"], bins=edges, include_lowest=True, duplicates="drop")
    rows: list[dict[str, Any]] = []
    weighted_error = 0.0
    total = len(source)
    for label, grp in source.groupby("calibration_bin", dropna=False, observed=False):
        if grp.empty:
            continue
        avg_pred = float(grp["predicted_p_win"].mean())
        actual = float(pd.to_numeric(grp["win"], errors="coerce").mean())
        error = abs(avg_pred - actual)
        weighted_error += error * (len(grp) / max(total, 1))
        rows.append(
            {
                "bin": str(label),
                "sample_count": int(len(grp)),
                "avg_predicted_p_win_pct": round(avg_pred * 100.0, 2),
                "actual_win_rate_pct": round(actual * 100.0, 2),
                "abs_error_pct": round(error * 100.0, 2),
            }
        )
    return {
        "status": "ok",
        "source": str(source["predicted_p_win_source"].mode().iloc[0]) if "predicted_p_win_source" in source.columns and not source["predicted_p_win_source"].dropna().empty else "unknown",
        "ece": round(weighted_error, 6),
        "ece_pct": round(weighted_error * 100.0, 2),
        "bins": rows,
    }


def _signal_decay_summary(df: pd.DataFrame, decay_days: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in sorted({int(day) for day in decay_days if int(day) > 0}):
        col = f"decay_{day}d_r"
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        rows.append(
            {
                "day": int(day),
                "sample_count": int(len(series)),
                "avg_decay_r": round(float(series.mean()), 4) if not series.empty else 0.0,
                "positive_rate_pct": round(float((series > 0).mean() * 100.0), 2) if not series.empty else 0.0,
            }
        )
    return rows


def _threshold_optimization(df: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for mode, grid in {
        "t1": settings.validation.threshold_grid_t1,
        "swing": settings.validation.threshold_grid_swing,
    }.items():
        mode_df = df[df["mode"] == mode].copy()
        candidates: list[dict[str, Any]] = []
        for threshold in sorted({float(value) for value in grid}):
            subset = mode_df[pd.to_numeric(mode_df["score"], errors="coerce") >= threshold].copy()
            summary = _summarize_trades(subset)
            candidates.append({"threshold": threshold, **summary})
        eligible = [
            row for row in candidates
            if int(row.get("trade_count", 0)) >= int(settings.signal_accuracy.min_trades_per_segment)
        ]
        eligible.sort(key=lambda row: (float(row.get("expectancy_r", 0.0)), float(row.get("profit_factor_r", 0.0)), int(row.get("trade_count", 0))), reverse=True)
        rows[mode] = {
            "current_live_threshold": _threshold_for_mode(settings, mode),
            "best_threshold": eligible[0] if eligible else {},
            "candidates": candidates,
        }
    return rows


def _false_positive_summary(df: pd.DataFrame, min_trades: int) -> dict[str, Any]:
    losers = df[pd.to_numeric(df["realized_r"], errors="coerce") < 0].copy()
    worst_recent = losers.sort_values(["realized_r", "date"], ascending=[True, False]).head(20)
    weak_groups: dict[str, list[dict[str, Any]]] = {}
    for label, group_cols in {
        "ticker": ["ticker"],
        "mode": ["mode"],
        "regime": ["regime_status"],
        "score_bucket": ["score_bucket"],
        "volatility_bucket": ["volatility_bucket"],
        "liquidity_bucket": ["liquidity_bucket"],
    }.items():
        grouped = _summarize_group(df, group_cols=group_cols)
        if grouped.empty:
            weak_groups[label] = []
            continue
        weak = grouped[
            (pd.to_numeric(grouped["trade_count"], errors="coerce") >= int(min_trades))
            & (
                (pd.to_numeric(grouped["expectancy_r"], errors="coerce") < 0)
                | (pd.to_numeric(grouped["profit_factor_r"], errors="coerce") < 1.0)
            )
        ].copy()
        weak_groups[label] = _records(weak.head(10))
    return {
        "negative_signal_count": int(len(losers)),
        "negative_signal_rate_pct": round(float((pd.to_numeric(df["realized_r"], errors="coerce") < 0).mean() * 100.0), 2) if not df.empty else 0.0,
        "weak_groups": weak_groups,
        "worst_false_positive_examples": _records(
            worst_recent[["date", "ticker", "mode", "score", "regime_status", "score_bucket", "outcome", "realized_r", "mae_r", "mfe_r"]],
            limit=20,
        ),
    }


def generate_signal_accuracy_audit(features: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    cfg = settings.signal_accuracy
    out_json = Path(cfg.output_json_path)
    by_ticker_path = Path(cfg.by_ticker_path)
    by_regime_path = Path(cfg.by_regime_path)
    by_score_bucket_path = Path(cfg.by_score_bucket_path)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    by_ticker_path.parent.mkdir(parents=True, exist_ok=True)
    by_regime_path.parent.mkdir(parents=True, exist_ok=True)
    by_score_bucket_path.parent.mkdir(parents=True, exist_ok=True)

    trades = _build_audit_trades(features=features, settings=settings)
    if trades.empty:
        payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "status": "no_trades",
            "message": "No complete signal outcomes available for accuracy audit",
            "report_paths": {
                "json": str(out_json),
                "by_ticker_csv": str(by_ticker_path),
                "by_regime_csv": str(by_regime_path),
                "by_score_bucket_csv": str(by_score_bucket_path),
            },
            "overall": _summarize_trades(trades),
        }
        pd.DataFrame().to_csv(by_ticker_path, index=False)
        pd.DataFrame().to_csv(by_regime_path, index=False)
        pd.DataFrame().to_csv(by_score_bucket_path, index=False)
        atomic_write_json(out_json, payload)
        return payload

    by_ticker = _summarize_group(trades, ["ticker"])
    by_regime = _summarize_group(trades, ["mode", "regime_status"])
    by_score_bucket = _summarize_group(trades, ["mode", "score_bucket"])
    by_ticker.to_csv(by_ticker_path, index=False)
    by_regime.to_csv(by_regime_path, index=False)
    by_score_bucket.to_csv(by_score_bucket_path, index=False)

    live_trades = trades[trades["passes_live_threshold"]].copy()
    precision_live = {
        "combined": [_precision_at_k(live_trades, int(k)) for k in cfg.precision_top_k],
        "by_mode": {
            mode: [_precision_at_k(live_trades, int(k), mode=mode) for k in cfg.precision_top_k]
            for mode in sorted(trades["mode"].dropna().unique().tolist())
        },
    }
    by_mode = {
        str(mode): _summarize_trades(grp)
        for mode, grp in trades.groupby("mode", dropna=False)
    }
    live_by_mode = {
        str(mode): _summarize_trades(grp)
        for mode, grp in live_trades.groupby("mode", dropna=False)
    }

    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "status": "ok",
        "message": "Signal accuracy audit generated",
        "input": {
            "feature_rows": int(len(features)),
            "audited_trade_count": int(len(trades)),
            "live_threshold_trade_count": int(len(live_trades)),
            "active_modes": list(settings.pipeline.active_modes),
            "max_signals_per_day": int(cfg.max_signals_per_day),
            "precision_top_k": [int(k) for k in cfg.precision_top_k],
            "horizon_days": {
                "t1": int(settings.model_v2.horizon_days_t1),
                "swing": int(settings.model_v2.horizon_days_swing),
            },
            "live_thresholds": {
                "t1": float(settings.pipeline.min_live_score_t1),
                "swing": float(settings.pipeline.min_live_score_swing),
            },
            "roundtrip_cost_pct": round(float(settings.backtest.buy_fee_pct + settings.backtest.sell_fee_pct + (2 * settings.backtest.slippage_pct)), 4),
        },
        "report_paths": {
            "json": str(out_json),
            "by_ticker_csv": str(by_ticker_path),
            "by_regime_csv": str(by_regime_path),
            "by_score_bucket_csv": str(by_score_bucket_path),
        },
        "overall": _summarize_trades(trades),
        "live_threshold": _summarize_trades(live_trades),
        "by_mode": by_mode,
        "live_by_mode": live_by_mode,
        "precision_at_k": precision_live,
        "calibration": _calibration_summary(live_trades if not live_trades.empty else trades, int(cfg.calibration_bins)),
        "signal_decay": _signal_decay_summary(live_trades if not live_trades.empty else trades, cfg.decay_days),
        "threshold_optimization": _threshold_optimization(trades, settings),
        "false_positive_summary": _false_positive_summary(live_trades if not live_trades.empty else trades, int(cfg.min_trades_per_segment)),
        "by_ticker_preview": _records(by_ticker.head(20)),
        "by_regime": _records(by_regime),
        "by_score_bucket": _records(by_score_bucket),
        "recent_trades": _records(trades.sort_values("date", ascending=False).head(30)),
    }
    atomic_write_json(out_json, payload)
    return payload
