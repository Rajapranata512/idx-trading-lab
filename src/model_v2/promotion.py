"""Automated promotion gate for model_v2.

Checks whether a model trained via walk-forward meets minimum quality
criteria before it can be promoted from shadow to live execution.
"""
from __future__ import annotations

from typing import Any


# Default gate thresholds (aligned with MODEL_V2_BLUEPRINT.md §7)
DEFAULT_GATE = {
    "min_oos_trades": 120,
    "min_profit_factor": 1.25,
    "min_expectancy": 0.0,
    "max_drawdown_pct": 12.0,
    "min_fold_profitable_pct": 0.60,  # at least 60% of folds must be profitable
}


def check_promotion_gate(
    fold_metrics: list[dict[str, float]],
    gate: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate whether a model passes the promotion gate.

    Parameters
    ----------
    fold_metrics : list[dict]
        One dict per walk-forward fold with keys:
        ``ProfitFactor``, ``Expectancy``, ``MaxDD``, ``Trades``.
    gate : dict, optional
        Override gate thresholds.  Defaults to ``DEFAULT_GATE``.

    Returns
    -------
    dict with:
        passed        : bool — overall pass/fail
        reasons       : list[str] — human-readable failure reasons (empty if passed)
        summary       : dict — aggregated metrics across folds
        fold_details  : list[dict] — per-fold pass/fail breakdown
    """
    cfg = {**DEFAULT_GATE, **(gate or {})}

    if not fold_metrics:
        return {
            "passed": False,
            "reasons": ["No fold metrics provided"],
            "summary": {},
            "fold_details": [],
        }

    # --- Aggregate metrics ---
    import numpy as np

    trades_list = [float(m.get("Trades", 0)) for m in fold_metrics]
    pf_list = [float(m.get("ProfitFactor", 0)) for m in fold_metrics]
    exp_list = [float(m.get("Expectancy", 0)) for m in fold_metrics]
    dd_list = [abs(float(m.get("MaxDD", 0))) for m in fold_metrics]

    total_trades = sum(trades_list)
    median_pf = float(np.median(pf_list))
    median_exp = float(np.median(exp_list))
    worst_dd = max(dd_list) if dd_list else 0.0

    # Per-fold profitability (PF > 1.0)
    n_profitable = sum(1 for pf in pf_list if pf > 1.0)
    profitable_pct = n_profitable / len(pf_list) if pf_list else 0.0

    summary = {
        "total_oos_trades": int(total_trades),
        "median_profit_factor": round(median_pf, 4),
        "median_expectancy": round(median_exp, 6),
        "worst_max_drawdown_pct": round(worst_dd, 2),
        "profitable_fold_pct": round(profitable_pct, 4),
        "n_folds": len(fold_metrics),
        "n_folds_profitable": n_profitable,
    }

    # --- Gate checks ---
    reasons: list[str] = []

    if total_trades < cfg["min_oos_trades"]:
        reasons.append(
            f"Total OOS trades ({int(total_trades)}) < minimum ({int(cfg['min_oos_trades'])})"
        )
    if median_pf < cfg["min_profit_factor"]:
        reasons.append(
            f"Median ProfitFactor ({median_pf:.4f}) < minimum ({cfg['min_profit_factor']:.2f})"
        )
    if median_exp <= cfg["min_expectancy"]:
        reasons.append(
            f"Median Expectancy ({median_exp:.6f}) <= minimum ({cfg['min_expectancy']:.4f})"
        )
    if worst_dd > cfg["max_drawdown_pct"]:
        reasons.append(
            f"Worst MaxDD ({worst_dd:.2f}%) > limit ({cfg['max_drawdown_pct']:.1f}%)"
        )
    if profitable_pct < cfg["min_fold_profitable_pct"]:
        reasons.append(
            f"Profitable folds ({profitable_pct:.0%}) < minimum ({cfg['min_fold_profitable_pct']:.0%})"
        )

    # --- Per-fold detail ---
    fold_details: list[dict[str, Any]] = []
    for i, m in enumerate(fold_metrics, start=1):
        pf = float(m.get("ProfitFactor", 0))
        fold_details.append({
            "fold": i,
            "trades": int(m.get("Trades", 0)),
            "profit_factor": round(pf, 4),
            "expectancy": round(float(m.get("Expectancy", 0)), 6),
            "max_dd_pct": round(abs(float(m.get("MaxDD", 0))), 2),
            "profitable": pf > 1.0,
        })

    return {
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "summary": summary,
        "fold_details": fold_details,
    }
