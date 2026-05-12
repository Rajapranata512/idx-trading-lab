"""Closed-loop feedback — retrain model from actual trade_fills.csv results.

Monitors live execution fills, computes realized performance metrics,
and triggers retraining when enough new data has accumulated. This
creates a virtuous cycle: model → signals → trades → fills → retrain → better model.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config import Settings
from src.model_v2.io import load_state, save_state
from src.model_v2.train import maybe_auto_train_model_v2


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except Exception:
        return default


def _profit_factor(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    gp = float(clean[clean > 0].sum())
    gl = float(-clean[clean < 0].sum())
    if gl <= 0:
        return 999.0 if gp > 0 else 0.0
    return gp / gl


def load_trade_fills(
    fills_path: str | Path,
    lookback_days: int = 90,
) -> pd.DataFrame:
    """Load and validate trade fills from CSV."""
    path = Path(fills_path)
    if not path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    required = {"executed_at", "ticker", "mode", "realized_r", "pnl_idr"}
    if not required.issubset(set(df.columns)):
        return pd.DataFrame()

    df["executed_at"] = pd.to_datetime(df["executed_at"], errors="coerce")
    df = df.dropna(subset=["executed_at", "ticker"]).copy()

    if lookback_days > 0:
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        df = df[df["executed_at"] >= cutoff].copy()

    df["realized_r"] = pd.to_numeric(df["realized_r"], errors="coerce")
    df["pnl_idr"] = pd.to_numeric(df["pnl_idr"], errors="coerce")
    return df.sort_values("executed_at").reset_index(drop=True)


def compute_fill_metrics(fills: pd.DataFrame) -> dict[str, Any]:
    """Compute aggregate performance metrics from fills."""
    if fills.empty:
        return {
            "total_fills": 0,
            "win_rate_pct": 0.0,
            "expectancy_r": 0.0,
            "profit_factor_r": 0.0,
            "total_pnl_idr": 0.0,
            "by_mode": {},
        }

    rr = pd.to_numeric(fills["realized_r"], errors="coerce").dropna()
    overall = {
        "total_fills": int(len(fills)),
        "win_rate_pct": round(float((rr > 0).mean() * 100), 2) if not rr.empty else 0.0,
        "expectancy_r": round(float(rr.mean()), 6) if not rr.empty else 0.0,
        "profit_factor_r": round(float(_profit_factor(rr)), 4),
        "total_pnl_idr": round(float(fills["pnl_idr"].sum()), 2),
    }

    by_mode: dict[str, dict[str, Any]] = {}
    for mode, grp in fills.groupby("mode", dropna=False):
        mode_rr = pd.to_numeric(grp["realized_r"], errors="coerce").dropna()
        by_mode[str(mode)] = {
            "fills": int(len(grp)),
            "win_rate_pct": round(float((mode_rr > 0).mean() * 100), 2) if not mode_rr.empty else 0.0,
            "expectancy_r": round(float(mode_rr.mean()), 6) if not mode_rr.empty else 0.0,
            "profit_factor_r": round(float(_profit_factor(mode_rr)), 4),
        }
    overall["by_mode"] = by_mode
    return overall


def maybe_closed_loop_retrain(
    scored_history: pd.DataFrame,
    settings: Settings,
) -> dict[str, Any]:
    """Check if closed-loop retrain conditions are met and trigger retrain.

    Conditions:
    1. Enough new fills since last retrain
    2. Minimum hours between retrains
    3. Fill performance meets minimum quality (prevents retraining on bad data)
    """
    cfg = settings.model_v2
    if not cfg.closed_loop_retrain_enabled:
        return {"status": "disabled", "message": "Closed-loop retrain is disabled"}

    state = load_state(cfg.closed_loop_state_path)
    now = datetime.utcnow()

    # Check minimum hours between retrains
    last_retrain = state.get("last_retrain_at", "")
    if last_retrain:
        try:
            last_dt = datetime.fromisoformat(last_retrain)
            hours_since = (now - last_dt).total_seconds() / 3600.0
            if hours_since < cfg.closed_loop_min_hours_between_retrain:
                return {
                    "status": "skipped_interval",
                    "message": f"Only {hours_since:.1f}h since last retrain (min: {cfg.closed_loop_min_hours_between_retrain}h)",
                    "hours_since_last": round(hours_since, 2),
                }
        except Exception:
            pass

    # Load fills
    fills = load_trade_fills(
        fills_path=settings.reconciliation.fills_csv_path,
        lookback_days=90,
    )

    if len(fills) < cfg.closed_loop_min_live_samples:
        return {
            "status": "skipped_insufficient_fills",
            "message": f"Only {len(fills)} fills (min: {cfg.closed_loop_min_live_samples})",
            "fill_count": int(len(fills)),
        }

    # Count new fills since last retrain
    last_fill_count = int(state.get("fill_count_at_last_retrain", 0))
    new_fills = len(fills) - last_fill_count
    if new_fills < cfg.closed_loop_min_new_fills:
        return {
            "status": "skipped_insufficient_new_fills",
            "message": f"Only {new_fills} new fills (min: {cfg.closed_loop_min_new_fills})",
            "new_fills": new_fills,
            "total_fills": int(len(fills)),
        }

    # Check fill quality
    metrics = compute_fill_metrics(fills)
    if metrics["profit_factor_r"] < cfg.closed_loop_min_profit_factor_r:
        return {
            "status": "skipped_quality_gate",
            "message": (
                f"Fill PF ({metrics['profit_factor_r']:.4f}) < minimum "
                f"({cfg.closed_loop_min_profit_factor_r:.2f}). "
                "Not retraining on consistently losing fills."
            ),
            "metrics": metrics,
        }

    if metrics["expectancy_r"] < cfg.closed_loop_min_expectancy_r:
        return {
            "status": "skipped_expectancy_gate",
            "message": (
                f"Fill expectancy ({metrics['expectancy_r']:.6f}) < minimum "
                f"({cfg.closed_loop_min_expectancy_r:.4f})"
            ),
            "metrics": metrics,
        }

    # All gates passed — trigger retrain with fills data blended in
    # Augment scored_history with fill outcomes for weight boost
    augmented_history = _augment_with_fills(scored_history, fills)

    train_result = maybe_auto_train_model_v2(
        scored_history=augmented_history,
        settings=settings,
        force=True,  # force retrain
    )

    # Save state
    new_state = {
        "last_retrain_at": now.isoformat(),
        "fill_count_at_last_retrain": int(len(fills)),
        "trigger_metrics": metrics,
        "train_result_status": train_result.get("status", "unknown"),
    }
    save_state(cfg.closed_loop_state_path, new_state)

    return {
        "status": "retrained",
        "message": f"Closed-loop retrain triggered with {len(fills)} fills",
        "fill_metrics": metrics,
        "train_result": train_result,
        "new_fills": new_fills,
    }


def _augment_with_fills(
    scored_history: pd.DataFrame,
    fills: pd.DataFrame,
) -> pd.DataFrame:
    """Blend fill outcomes into scored history for retraining.

    Recent fills get 2x weight by being duplicated, so the model
    learns more from actual execution results than historical simulations.
    """
    if scored_history.empty or fills.empty:
        return scored_history.copy()

    history = scored_history.copy()

    # Mark fills with actual outcomes in the history
    fills_lookup = {}
    for _, fill in fills.iterrows():
        ticker = str(fill.get("ticker", "")).strip().upper()
        date = pd.to_datetime(fill.get("executed_at"), errors="coerce")
        if pd.isna(date) or not ticker:
            continue
        date_str = date.strftime("%Y-%m-%d")
        key = f"{ticker}:{date_str}"
        fills_lookup[key] = {
            "realized_r": _safe_float(fill.get("realized_r"), 0.0),
            "pnl_idr": _safe_float(fill.get("pnl_idr"), 0.0),
        }

    if not fills_lookup:
        return history

    # Tag rows that have actual fill data
    history["_fill_key"] = (
        history["ticker"].astype(str).str.upper() + ":" +
        pd.to_datetime(history["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    )
    has_fill = history["_fill_key"].isin(fills_lookup.keys())

    # Duplicate fill rows for 2x weight
    fill_rows = history[has_fill].copy()
    if not fill_rows.empty:
        history = pd.concat([history, fill_rows], ignore_index=True, sort=False)

    history.drop(columns=["_fill_key"], inplace=True, errors="ignore")
    return history
