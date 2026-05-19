"""Automated promotion gate for model_v2.

Checks whether a model trained via walk-forward meets minimum quality
criteria before it can be promoted from shadow to live execution.
"""
from __future__ import annotations

from typing import Any
import json
import random
from pathlib import Path

import pandas as pd

from src.config import Settings


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


def evaluate_and_update_model_v2_promotion(settings: Settings) -> dict[str, Any]:
    """Evaluate walk-forward and live performance to promote model_v2."""
    cfg = settings.model_v2.promotion
    if not cfg.enabled:
        return {
            "status": "disabled",
            "message": "Promotion logic disabled in settings",
            "rollout_pct": 0,
            "live_active": False,
        }

    state_path = Path(cfg.state_path)
    state = {
        "rollout_level_idx": 0,
        "consecutive_passes": 0,
    }
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    rollout_levels = cfg.rollout_levels_pct
    idx = state.get("rollout_level_idx", 0)
    consecutive_passes = state.get("consecutive_passes", 0)
    current_rollout_pct = rollout_levels[idx] if idx < len(rollout_levels) else rollout_levels[-1]

    # Evaluate walk-forward gate
    wf_path = Path("reports/walk_forward_metrics.json")
    wf_passed = False
    if wf_path.exists():
        try:
            wf_data = json.loads(wf_path.read_text(encoding="utf-8"))
            folds = wf_data.get("folds", [])
            gate_res = check_promotion_gate(folds)
            wf_passed = gate_res.get("passed", False)
        except Exception:
            pass

    # Evaluate live performance if rollout_pct > 0
    live_ok = True
    rollback = False
    if current_rollout_pct > 0:
        lr_path = Path("reports/live_reconciliation.json")
        if lr_path.exists():
            try:
                lr_data = json.loads(lr_path.read_text(encoding="utf-8"))
                realized = lr_data.get("realized_kpi", {})
                cov = lr_data.get("coverage", {})
                samples = realized.get("samples", 0)
                
                if samples >= cfg.min_live_samples:
                    pf = realized.get("profit_factor_r", 0.0)
                    exp = realized.get("expectancy_r", 0.0)
                    match_rate = cov.get("entry_match_rate_pct", 0.0)
                    
                    if pf < cfg.rollback_profit_factor_r or exp < cfg.rollback_expectancy_r:
                        rollback = True
                        live_ok = False
                    elif pf >= cfg.min_profit_factor_r and exp >= cfg.min_expectancy_r and match_rate >= cfg.min_entry_match_rate_pct:
                        live_ok = True
                    else:
                        live_ok = False 
                else:
                    live_ok = False 
            except Exception:
                live_ok = False

    if rollback and cfg.rollback_on_fail:
        idx = 0
        consecutive_passes = 0
        status_msg = "Rolled back to 0% due to poor live performance."
    else:
        if wf_passed and (current_rollout_pct == 0 or live_ok):
            consecutive_passes += 1
        else:
            consecutive_passes = 0

        if consecutive_passes >= cfg.consecutive_passes_required:
            if idx < len(rollout_levels) - 1:
                idx += 1
                consecutive_passes = 0
            
        status_msg = "Evaluated promotion criteria."

    state["rollout_level_idx"] = idx
    state["consecutive_passes"] = consecutive_passes
    
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    new_rollout_pct = rollout_levels[idx] if idx < len(rollout_levels) else rollout_levels[-1]

    return {
        "status": "ok",
        "message": status_msg,
        "rollout_pct": new_rollout_pct,
        "live_active": new_rollout_pct > 0,
        "consecutive_passes": consecutive_passes,
    }


def apply_model_v2_rollout_selection(
    filtered_combined: pd.DataFrame,
    settings: Settings,
    promotion_info: dict[str, Any],
    shadow_csv_path: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Applies the probabilistic rollout of model_v2 signals to live execution."""
    rollout_pct = promotion_info.get("rollout_pct", 0)
    if rollout_pct <= 0 or not Path(shadow_csv_path).exists():
        return filtered_combined, filtered_combined.copy().iloc[0:0], {
            "status": "skipped",
            "message": "Rollout is 0% or shadow signals missing.",
            "rollout_pct": rollout_pct,
            "live_active": False,
            "selected_count": 0
        }
        
    shadow_df = pd.read_csv(shadow_csv_path)
    if shadow_df.empty:
        return filtered_combined, filtered_combined.copy().iloc[0:0], {
            "status": "skipped",
            "message": "Shadow signals empty.",
            "rollout_pct": rollout_pct,
            "live_active": True,
            "selected_count": 0
        }
        
    promoted_selection = shadow_df.copy()
    promoted_selection["source"] = "model_v2"
    
    filtered_combined = filtered_combined.copy()
    if "source" not in filtered_combined.columns:
        filtered_combined["source"] = "v1"
        
    accepted_shadow = []
    p = rollout_pct / 100.0
    for _, row in shadow_df.iterrows():
        if random.random() <= p:
            accepted_shadow.append(row)
            
    if not accepted_shadow:
        return filtered_combined, filtered_combined.copy().iloc[0:0], {
            "status": "applied",
            "message": "Rollout active but no shadow signals selected due to probability.",
            "rollout_pct": rollout_pct,
            "live_active": True,
            "selected_count": 0
        }
        
    accepted_df = pd.DataFrame(accepted_shadow)
    accepted_df["source"] = "model_v2"
    
    accepted_tickers = accepted_df["ticker"].tolist()
    filtered_combined = filtered_combined[~filtered_combined["ticker"].isin(accepted_tickers)]
    
    final_combined = pd.concat([filtered_combined, accepted_df], ignore_index=True)
    
    if "score" in final_combined.columns:
        final_combined = final_combined.sort_values(by="score", ascending=False)
    
    return final_combined, accepted_df, {
        "status": "applied",
        "message": f"Mixed model_v2 signals with {rollout_pct}% probability.",
        "rollout_pct": rollout_pct,
        "live_active": True,
        "selected_count": len(accepted_df)
    }

