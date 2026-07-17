"""Automated promotion gate for model_v2.

Checks whether a model trained via walk-forward meets minimum quality
criteria before it can be promoted from shadow to live execution.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
import json
import math
from pathlib import Path

import pandas as pd

from src.config import Settings
from src.model_v2.io import load_model_bundle, model_artifact_path, model_metadata_path
from src.runtime import active_modes as resolve_active_modes


# Default gate thresholds (aligned with MODEL_V2_BLUEPRINT.md §7)
DEFAULT_GATE = {
    "min_oos_trades": 120,
    "min_profit_factor": 1.25,
    "min_expectancy": 0.03,
    "max_drawdown_pct": 12.0,
    "min_fold_profitable_pct": 0.60,  # at least 60% of folds must be profitable
    "min_folds": 5,
}


def _model_readiness(settings: Settings) -> dict[str, Any]:
    cfg = settings.model_v2.promotion
    modes = resolve_active_modes(settings)
    details: dict[str, Any] = {}
    signature_parts: list[str] = []
    ready = bool(modes)

    for mode in modes:
        artifact_path = model_artifact_path(settings.model_v2.model_dir, mode)
        metadata_path = model_metadata_path(settings.model_v2.model_dir, mode)
        model, metadata = load_model_bundle(settings.model_v2.model_dir, mode)
        metadata = metadata if isinstance(metadata, dict) else {}

        calibration = metadata.get("calibration", {}) if isinstance(metadata, dict) else {}
        holdout_ok = bool(calibration.get("evaluated_on_holdout", False))
        ece = float(calibration.get("ece", 999.0) or 999.0)
        ece_ok = ece <= float(cfg.max_calibration_ece_pct) / 100.0
        artifact_exists = artifact_path.exists() and artifact_path.stat().st_size > 0
        artifact_loadable = model is not None
        metadata_ok = metadata_path.exists() and bool(metadata)
        mode_ready = bool(artifact_exists and artifact_loadable and metadata_ok and holdout_ok and ece_ok)
        ready = ready and mode_ready

        version = str(metadata.get("trained_at", metadata.get("saved_at", "")))
        signature_parts.append(f"{mode}:{version}")
        details[str(mode)] = {
            "ready": mode_ready,
            "artifact_ok": artifact_exists and artifact_loadable,
            "artifact_exists": artifact_exists,
            "artifact_loadable": artifact_loadable,
            "metadata_ok": metadata_ok,
            "holdout_calibration_ok": holdout_ok,
            "calibration_ece": ece if ece < 999.0 else None,
            "calibration_ece_limit": float(cfg.max_calibration_ece_pct) / 100.0,
            "version": version,
        }

    return {
        "passed": ready,
        "active_modes": [str(mode) for mode in modes],
        "model_signature": "|".join(signature_parts),
        "modes": details,
    }


def _accuracy_gate_from_report(settings: Settings) -> dict[str, Any]:
    cfg = settings.model_v2.promotion
    path = Path(settings.model_v2_accuracy.output_json_path)
    if not path.exists():
        return {"passed": False, "status": "missing_accuracy_audit", "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "passed": False,
            "status": "accuracy_audit_read_error",
            "path": str(path),
            "message": str(exc),
        }

    status = str(payload.get("status", ""))
    source = payload.get("model_source", {}) if isinstance(payload, dict) else {}
    v2 = payload.get("v2_recommended", {}) if isinstance(payload, dict) else {}
    calibration = payload.get("calibration_v2_recommended", {}) if isinstance(payload, dict) else {}
    trades = int(v2.get("trade_count", 0) or 0)
    expectancy = float(v2.get("expectancy_r", 0.0) or 0.0)
    profit_factor = float(v2.get("profit_factor_r", 0.0) or 0.0)
    ece_pct = float(calibration.get("ece_pct", 999.0) or 999.0)
    has_non_model = bool(source.get("has_non_model", source.get("has_fallback", False)))

    age_days: float | None = None
    generated_at = str(payload.get("generated_at", ""))
    if generated_at:
        try:
            generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            now = datetime.now(generated.tzinfo) if generated.tzinfo else datetime.utcnow()
            age_days = max(0.0, (now - generated).total_seconds() / 86400.0)
        except Exception:
            age_days = None

    checks = {
        "status_ok": status == "ok",
        "model_source_ok": not has_non_model,
        "trade_count_ok": trades >= int(cfg.min_accuracy_trades),
        "expectancy_ok": expectancy >= float(cfg.min_accuracy_expectancy_r),
        "profit_factor_ok": profit_factor >= float(cfg.min_accuracy_profit_factor_r),
        "calibration_ok": ece_pct <= float(cfg.max_calibration_ece_pct),
        "freshness_ok": age_days is not None and age_days <= float(cfg.max_accuracy_age_days),
    }
    return {
        "passed": all(checks.values()),
        "status": status,
        "path": str(path),
        "generated_at": generated_at,
        "age_days": round(age_days, 3) if age_days is not None else None,
        "trade_count": trades,
        "expectancy_r": expectancy,
        "profit_factor_r": profit_factor,
        "calibration_ece_pct": ece_pct if ece_pct < 999.0 else None,
        "checks": checks,
    }


def _extract_walk_forward_folds(payload: dict[str, Any]) -> list[dict[str, float]]:
    """Return fold metric rows from both legacy and current walk-forward payloads."""
    if not isinstance(payload, dict):
        return []
    root_folds = payload.get("folds", [])
    if isinstance(root_folds, list) and root_folds:
        return [row for row in root_folds if isinstance(row, dict)]

    wf = payload.get("walk_forward", payload)
    if not isinstance(wf, dict):
        return []
    modes = wf.get("modes", {})
    if not isinstance(modes, dict):
        return []

    rows: list[dict[str, float]] = []
    for mode_payload in modes.values():
        if not isinstance(mode_payload, dict):
            continue
        for fold in mode_payload.get("folds", []) or []:
            if not isinstance(fold, dict):
                continue
            metrics = fold.get("metrics", fold)
            if isinstance(metrics, dict):
                rows.append(metrics)
    return rows


def _live_gate_from_reconciliation(settings: Settings) -> tuple[bool, bool, dict[str, Any]]:
    cfg = settings.model_v2.promotion
    lr_path = Path(settings.reconciliation.output_json_path)
    if not lr_path.exists():
        return False, False, {"status": "missing_live_reconciliation"}
    try:
        lr_data = json.loads(lr_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, False, {"status": "read_error", "message": str(exc)}

    realized = lr_data.get("realized_kpi", {}) if isinstance(lr_data, dict) else {}
    cov = lr_data.get("coverage", {}) if isinstance(lr_data, dict) else {}
    samples = int(realized.get("samples", 0) or 0)
    pf = float(realized.get("profit_factor_r", 0.0) or 0.0)
    exp = float(realized.get("expectancy_r", 0.0) or 0.0)
    match_rate = float(cov.get("entry_match_rate_pct", 0.0) or 0.0)

    payload = {
        "status": str(lr_data.get("status", "")) if isinstance(lr_data, dict) else "",
        "samples": samples,
        "profit_factor_r": pf,
        "expectancy_r": exp,
        "entry_match_rate_pct": match_rate,
    }
    if samples < int(cfg.min_live_samples):
        payload["reason"] = "insufficient_live_samples"
        return False, False, payload

    rollback = bool(pf < float(cfg.rollback_profit_factor_r) or exp < float(cfg.rollback_expectancy_r))
    passed = bool(
        pf >= float(cfg.min_profit_factor_r)
        and exp >= float(cfg.min_expectancy_r)
        and match_rate >= float(cfg.min_entry_match_rate_pct)
    )
    payload["reason"] = "rollback_triggered" if rollback else ("live_gate_passed" if passed else "live_gate_failed")
    return passed, rollback, payload


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
    if len(fold_metrics) < int(cfg["min_folds"]):
        reasons.append(
            f"Walk-forward folds ({len(fold_metrics)}) < minimum ({int(cfg['min_folds'])})"
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
    model_gate = _model_readiness(settings)
    accuracy_gate = _accuracy_gate_from_report(settings)
    model_signature = str(model_gate.get("model_signature", ""))
    previous_signature = str(state.get("model_signature", ""))
    model_changed = bool(previous_signature and previous_signature != model_signature)
    if model_changed:
        idx = 0
        consecutive_passes = 0
        current_rollout_pct = rollout_levels[0]

    wf_path_candidates = [Path("reports/walk_forward_metrics.json"), Path("reports/backtest_metrics.json")]
    wf_gate: dict[str, Any] = {"passed": False, "reasons": ["No walk-forward metrics found"]}
    for wf_path in wf_path_candidates:
        if not wf_path.exists():
            continue
        try:
            wf_data = json.loads(wf_path.read_text(encoding="utf-8"))
            folds = _extract_walk_forward_folds(wf_data)
            wf_gate = check_promotion_gate(folds)
            break
        except Exception as exc:
            wf_gate = {"passed": False, "reasons": [str(exc)]}

    live_ok, rollback, live_gate = _live_gate_from_reconciliation(settings)
    wf_passed = bool(wf_gate.get("passed", False))
    gate_passed = bool(
        wf_passed
        and model_gate.get("passed", False)
        and accuracy_gate.get("passed", False)
    )
    safety_blocked = not gate_passed

    if (rollback or (current_rollout_pct > 0 and safety_blocked)) and cfg.rollback_on_fail:
        idx = 0
        consecutive_passes = 0
        status_msg = "Rolled back to 0% because a production safety gate failed."
        reason = "rollback_triggered" if rollback else "safety_gate_rollback"
    else:
        if gate_passed and (current_rollout_pct == 0 or live_ok):
            consecutive_passes += 1
        else:
            consecutive_passes = 0

        if consecutive_passes >= cfg.consecutive_passes_required:
            if idx < len(rollout_levels) - 1:
                idx += 1
                consecutive_passes = 0
            
        status_msg = "Evaluated promotion criteria."
        reason = "promotion_gate_passed" if gate_passed else "promotion_gate_failed"

    state["rollout_level_idx"] = idx
    state["consecutive_passes"] = consecutive_passes
    state["model_signature"] = model_signature
    state["current_rollout_pct"] = rollout_levels[idx] if idx < len(rollout_levels) else rollout_levels[-1]
    state["last_evaluated_at"] = datetime.utcnow().isoformat()
    state["last_reason"] = reason
    state["final_decision_ready"] = bool(
        state["current_rollout_pct"] == 100
        and gate_passed
        and live_ok
    )

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    new_rollout_pct = rollout_levels[idx] if idx < len(rollout_levels) else rollout_levels[-1]

    return {
        "status": "ok",
        "message": status_msg,
        "reason": reason,
        "rollout_pct": new_rollout_pct,
        "live_active": new_rollout_pct > 0,
        "final_decision_ready": bool(state["final_decision_ready"]),
        "consecutive_passes": consecutive_passes,
        "model_changed": model_changed,
        "model_gate": model_gate,
        "accuracy_gate": accuracy_gate,
        "walk_forward_gate": wf_gate,
        "live_gate": live_gate,
    }


def apply_model_v2_rollout_selection(
    filtered_combined: pd.DataFrame,
    settings: Settings,
    promotion_info: dict[str, Any],
    shadow_csv_path: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Apply deterministic model_v2 rollout and backfill unused slots with v1."""
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

    filtered_combined = filtered_combined.copy()
    if "source" not in filtered_combined.columns:
        filtered_combined["source"] = "v1"

    max_positions = max(1, int(settings.risk.max_positions))
    v2_slots = max(1, int(math.ceil(max_positions * (float(rollout_pct) / 100.0))))
    shadow_ranked = shadow_df.copy()
    source_ok = (
        shadow_ranked.get("shadow_model_source", pd.Series("", index=shadow_ranked.index))
        .astype(str)
        .str.lower()
        .eq("model")
    )
    recommended = (
        shadow_ranked.get("shadow_recommended", pd.Series(False, index=shadow_ranked.index))
        .astype(str)
        .str.lower()
        .isin({"true", "1", "yes"})
    )
    shadow_ranked = shadow_ranked[source_ok & recommended].copy()
    if shadow_ranked.empty:
        v1_fill = filtered_combined.copy()
        if "score" in v1_fill.columns:
            v1_fill = v1_fill.sort_values("score", ascending=False)
        v1_fill = v1_fill.head(max_positions).copy()
        v1_fill["model_v2_live_selected"] = False
        v1_fill["model_v2_rollout_pct"] = int(rollout_pct)
        return filtered_combined.reset_index(drop=True), v1_fill.reset_index(drop=True), {
            "status": "blocked_no_valid_model_v2",
            "message": "No trained-model V2 recommendation was eligible; using V1 backfill only.",
            "rollout_pct": rollout_pct,
            "live_active": True,
            "v2_slot_count": 0,
            "v1_backfill_count": int(len(v1_fill)),
            "selected_count": int(len(v1_fill)),
        }
    sort_cols = [col for col in ["shadow_expected_r", "shadow_p_win", "score"] if col in shadow_ranked.columns]
    if sort_cols:
        shadow_ranked = shadow_ranked.sort_values(sort_cols, ascending=[False] * len(sort_cols)).copy()

    accepted_df = shadow_ranked.head(v2_slots).copy()
    accepted_df["source"] = "model_v2"
    accepted_df["model_v2_live_selected"] = True
    accepted_df["model_v2_rollout_pct"] = int(rollout_pct)
    
    accepted_tickers = set(accepted_df["ticker"].astype(str).str.upper().tolist())
    v1_pool = filtered_combined[
        ~filtered_combined["ticker"].astype(str).str.upper().isin(accepted_tickers)
    ].copy()
    if "score" in v1_pool.columns:
        v1_pool = v1_pool.sort_values("score", ascending=False).copy()
    v1_fill = v1_pool.head(max(0, max_positions - len(accepted_df))).copy()
    if not v1_fill.empty:
        v1_fill["model_v2_live_selected"] = False
        v1_fill["model_v2_rollout_pct"] = int(rollout_pct)

    live_selection = pd.concat([accepted_df, v1_fill], ignore_index=True, sort=False)
    final_combined = pd.concat([accepted_df, v1_pool], ignore_index=True, sort=False)
    
    if "score" in final_combined.columns:
        final_combined = final_combined.sort_values(by="score", ascending=False)
    
    return final_combined.reset_index(drop=True), live_selection.reset_index(drop=True), {
        "status": "live_rollout",
        "message": f"Applied deterministic model_v2 rollout with v1 backfill at {rollout_pct}%.",
        "rollout_pct": rollout_pct,
        "live_active": True,
        "v2_slot_count": int(len(accepted_df)),
        "v1_backfill_count": int(len(v1_fill)),
        "selected_count": int(len(live_selection)),
    }

