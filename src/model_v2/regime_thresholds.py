"""Regime-aware threshold tuning for model_v2 predictions.

Different market regimes (risk_on vs risk_off) require different
probability thresholds for trade entry. This module tunes thresholds
per regime using walk-forward grid search to maximize risk-adjusted returns.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# Default thresholds per regime per mode
DEFAULT_REGIME_THRESHOLDS = {
    "t1": {
        "risk_on": 0.50,    # more permissive in bullish market
        "risk_off": 0.60,   # stricter in bearish market
        "default": 0.52,
    },
    "swing": {
        "risk_on": 0.52,
        "risk_off": 0.62,
        "default": 0.55,
    },
}


def get_regime_threshold(
    mode: str,
    regime: str,
    custom_thresholds: dict[str, dict[str, float]] | None = None,
) -> float:
    """Return the probability threshold for a given mode + regime combo."""
    source = custom_thresholds or DEFAULT_REGIME_THRESHOLDS
    mode_key = str(mode).strip().lower()
    regime_key = str(regime).strip().lower()

    mode_thresholds = source.get(mode_key, source.get("default", {}))
    if isinstance(mode_thresholds, dict):
        return float(mode_thresholds.get(regime_key, mode_thresholds.get("default", 0.55)))
    return 0.55


def tune_regime_thresholds(
    probabilities: pd.Series,
    returns: pd.Series,
    regimes: pd.Series,
    mode: str,
    grid: list[float] | None = None,
    metric: str = "expectancy",
) -> dict[str, Any]:
    """Tune probability thresholds per regime via grid search.

    For each regime bucket, finds the threshold that maximizes the chosen
    metric (expectancy or profit_factor) over the given probabilities and returns.

    Parameters
    ----------
    probabilities : Series
        Predicted win probabilities (0-1).
    returns : Series
        Realized R-multiples for each row.
    regimes : Series
        Regime labels (``"risk_on"`` or ``"risk_off"``).
    mode : str
        Trading mode (``"t1"`` or ``"swing"``).
    grid : list[float], optional
        Threshold candidates to evaluate. Defaults to 0.40-0.75 in 0.02 steps.
    metric : str
        ``"expectancy"`` or ``"profit_factor"``.

    Returns
    -------
    dict with:
        thresholds_by_regime : dict[str, float]
        evaluation : list[dict] — per-regime per-threshold results
    """
    if grid is None:
        grid = [round(x, 2) for x in np.arange(0.40, 0.76, 0.02)]

    df = pd.DataFrame({
        "prob": pd.to_numeric(probabilities, errors="coerce"),
        "ret": pd.to_numeric(returns, errors="coerce"),
        "regime": regimes.astype(str).str.strip().str.lower(),
    }).dropna()

    if df.empty:
        return {
            "thresholds_by_regime": DEFAULT_REGIME_THRESHOLDS.get(mode, {}),
            "evaluation": [],
            "status": "no_data",
        }

    evaluation: list[dict[str, Any]] = []
    best_thresholds: dict[str, float] = {}

    for regime, grp in df.groupby("regime"):
        best_score = -999.0
        best_threshold = 0.55

        for threshold in grid:
            selected = grp[grp["prob"] >= threshold]
            if len(selected) < 5:
                continue

            if metric == "profit_factor":
                gp = float(selected["ret"][selected["ret"] > 0].sum())
                gl = float(-selected["ret"][selected["ret"] < 0].sum())
                score = (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0)
            else:  # expectancy
                score = float(selected["ret"].mean())

            win_rate = float((selected["ret"] > 0).mean() * 100)
            n_trades = int(len(selected))

            evaluation.append({
                "regime": str(regime),
                "threshold": threshold,
                "metric": metric,
                "score": round(score, 6),
                "n_trades": n_trades,
                "win_rate_pct": round(win_rate, 2),
            })

            if score > best_score:
                best_score = score
                best_threshold = threshold

        best_thresholds[str(regime)] = round(best_threshold, 4)

    # Fallback for missing regimes
    default_thresholds = DEFAULT_REGIME_THRESHOLDS.get(mode, {})
    for regime_key in ["risk_on", "risk_off", "default"]:
        if regime_key not in best_thresholds:
            best_thresholds[regime_key] = float(default_thresholds.get(regime_key, 0.55))

    return {
        "thresholds_by_regime": best_thresholds,
        "evaluation": sorted(evaluation, key=lambda x: (x["regime"], -x["score"])),
        "status": "ok",
        "mode": mode,
    }


def apply_regime_filter(
    candidates: pd.DataFrame,
    regimes: pd.Series,
    mode: str,
    custom_thresholds: dict[str, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """Filter candidates by regime-aware probability thresholds.

    Returns only rows where shadow_p_win >= regime-specific threshold.
    """
    if candidates.empty or "shadow_p_win" not in candidates.columns:
        return candidates.copy()

    df = candidates.copy()
    df["_regime"] = regimes.values if len(regimes) == len(df) else "default"

    thresholds = []
    for _, row in df.iterrows():
        regime = str(row.get("_regime", "default")).strip().lower()
        t = get_regime_threshold(mode, regime, custom_thresholds)
        thresholds.append(t)

    df["_regime_threshold"] = thresholds
    result = df[df["shadow_p_win"] >= df["_regime_threshold"]].copy()
    result.drop(columns=["_regime", "_regime_threshold"], inplace=True, errors="ignore")
    return result
