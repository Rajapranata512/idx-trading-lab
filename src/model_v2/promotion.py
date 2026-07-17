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
from src.model_v2.meta_filter import apply_bayesian_ticker_edge_filter
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


def _model_readiness(settings: Settings, mode: str | None = None) -> dict[str, Any]:
    cfg = settings.model_v2.promotion
    modes = [str(mode).lower()] if mode else resolve_active_modes(settings)
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
        holdout_auc = float(calibration.get("holdout_auc", 0.0) or 0.0)
        holdout_auc_ok = holdout_auc >= float(cfg.min_holdout_auc)
        artifact_exists = artifact_path.exists() and artifact_path.stat().st_size > 0
        artifact_loadable = model is not None
        metadata_ok = metadata_path.exists() and bool(metadata)
        mode_ready = bool(
            artifact_exists
            and artifact_loadable
            and metadata_ok
            and holdout_ok
            and ece_ok
            and holdout_auc_ok
        )
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
            "holdout_auc": holdout_auc,
            "holdout_auc_minimum": float(cfg.min_holdout_auc),
            "holdout_auc_ok": holdout_auc_ok,
            "walk_forward": metadata.get("walk_forward", {}),
            "version": version,
        }

    return {
        "passed": ready,
        "active_modes": [str(mode) for mode in modes],
        "model_signature": "|".join(signature_parts),
        "modes": details,
    }


def _accuracy_gate_from_report(
    settings: Settings,
    mode: str | None = None,
    expected_model_version: str = "",
) -> dict[str, Any]:
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
    mode_key = str(mode).strip().lower() if mode else ""
    if mode_key:
        v2 = (payload.get("final_eligible_by_mode", {}) or {}).get(mode_key, {})
        calibration = (payload.get("calibration_by_mode", {}) or {}).get(mode_key, {})
        mode_source = (source.get("mode_sources", {}) or {}).get(mode_key, {})
        has_non_model = str(mode_source.get("source", "")).strip().lower() != "model"
        audit_model_version = str(mode_source.get("version", ""))
    else:
        v2 = payload.get("final_eligible", payload.get("v2_recommended", {}))
        calibration = payload.get("calibration_v2_recommended", {})
        has_non_model = bool(source.get("has_non_model", source.get("has_fallback", False)))
        audit_model_version = ""
    trades = int(v2.get("trade_count", 0) or 0)
    expectancy = float(v2.get("expectancy_r", 0.0) or 0.0)
    profit_factor = float(v2.get("profit_factor_r", 0.0) or 0.0)
    ece_pct = float(calibration.get("ece_pct", 999.0) or 999.0)

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
        "model_version_ok": (
            not expected_model_version
            or audit_model_version == str(expected_model_version)
        ),
    }
    return {
        "passed": all(checks.values()),
        "status": status,
        "mode": mode_key or "combined",
        "path": str(path),
        "generated_at": generated_at,
        "audit_model_version": audit_model_version,
        "expected_model_version": str(expected_model_version),
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


def _live_gate_from_reconciliation(
    settings: Settings,
    mode: str | None = None,
) -> tuple[bool, bool, dict[str, Any]]:
    cfg = settings.model_v2.promotion
    lr_path = Path(settings.reconciliation.output_json_path)
    if not lr_path.exists():
        return False, False, {"status": "missing_live_reconciliation"}
    try:
        lr_data = json.loads(lr_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, False, {"status": "read_error", "message": str(exc)}

    mode_key = str(mode).strip().lower() if mode else ""
    mode_payload = (
        (lr_data.get("by_mode", {}) or {}).get(mode_key, {})
        if mode_key and isinstance(lr_data, dict)
        else {}
    )
    source_payload = mode_payload if isinstance(mode_payload, dict) and mode_payload else lr_data
    realized = source_payload.get("realized_kpi", source_payload) if isinstance(source_payload, dict) else {}
    cov = source_payload.get("coverage", lr_data.get("coverage", {})) if isinstance(source_payload, dict) else {}
    samples = int(realized.get("samples", 0) or 0)
    pf = float(realized.get("profit_factor_r", 0.0) or 0.0)
    exp = float(realized.get("expectancy_r", 0.0) or 0.0)
    match_rate = float(cov.get("entry_match_rate_pct", 0.0) or 0.0)

    payload = {
        "status": str(lr_data.get("status", "")) if isinstance(lr_data, dict) else "",
        "mode": mode_key or "combined",
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
    """Evaluate and update independent promotion state for every active mode."""
    cfg = settings.model_v2.promotion
    if not cfg.enabled:
        return {
            "status": "disabled",
            "message": "Promotion logic disabled in settings",
            "rollout_pct": 0,
            "live_active": False,
        }

    state_path = Path(cfg.state_path)
    state: dict[str, Any] = {"modes": {}}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not isinstance(state.get("modes"), dict):
        state["modes"] = {}

    rollout_levels = [int(value) for value in cfg.rollout_levels_pct]
    active_modes = [str(mode).lower() for mode in resolve_active_modes(settings)]
    evaluation_date = datetime.utcnow().date().isoformat()
    mode_results: dict[str, Any] = {}
    rollout_by_mode: dict[str, int] = {}
    final_by_mode: dict[str, bool] = {}

    for mode in active_modes:
        mode_state = state["modes"].get(
            mode,
            {
                "rollout_level_idx": 0,
                "consecutive_passes": 0,
                "shadow_session_dates": [],
            },
        )
        idx = min(max(int(mode_state.get("rollout_level_idx", 0)), 0), len(rollout_levels) - 1)
        consecutive_passes = int(mode_state.get("consecutive_passes", 0))
        current_rollout_pct = rollout_levels[idx]

        model_gate = _model_readiness(settings, mode=mode)
        mode_model = (model_gate.get("modes", {}) or {}).get(mode, {})
        accuracy_gate = _accuracy_gate_from_report(
            settings,
            mode=mode,
            expected_model_version=str(mode_model.get("version", "")),
        )
        walk_forward = mode_model.get("walk_forward", {}) if isinstance(mode_model, dict) else {}
        folds = [
            fold.get("metrics", fold)
            for fold in (walk_forward.get("folds", []) or [])
            if isinstance(fold, dict)
        ]
        wf_gate = check_promotion_gate(folds)
        live_ok, rollback, live_gate = _live_gate_from_reconciliation(settings, mode=mode)

        model_signature = str(model_gate.get("model_signature", ""))
        previous_signature = str(mode_state.get("model_signature", ""))
        model_changed = bool(previous_signature and previous_signature != model_signature)
        if model_changed:
            idx = 0
            consecutive_passes = 0
            current_rollout_pct = rollout_levels[0]

        shadow_dates = [
            str(value)
            for value in (mode_state.get("shadow_session_dates", []) or [])
            if str(value)
        ]
        if model_changed:
            shadow_dates = []
        source_ready = bool(
            mode_model.get("artifact_ok", False)
            and accuracy_gate.get("status") == "ok"
            and accuracy_gate.get("checks", {}).get("model_source_ok", False)
        )
        if source_ready and evaluation_date not in shadow_dates:
            shadow_dates.append(evaluation_date)
        shadow_dates = sorted(set(shadow_dates))[-120:]
        shadow_sessions_ok = len(shadow_dates) >= int(cfg.shadow_sessions_required)

        gate_passed = bool(
            model_gate.get("passed", False)
            and accuracy_gate.get("passed", False)
            and wf_gate.get("passed", False)
            and shadow_sessions_ok
        )
        safety_blocked = not gate_passed
        if (rollback or (current_rollout_pct > 0 and safety_blocked)) and cfg.rollback_on_fail:
            idx = 0
            consecutive_passes = 0
            reason = "rollback_triggered" if rollback else "safety_gate_rollback"
        else:
            can_accumulate_pass = gate_passed and (current_rollout_pct == 0 or live_ok)
            consecutive_passes = consecutive_passes + 1 if can_accumulate_pass else 0
            if consecutive_passes >= int(cfg.consecutive_passes_required):
                if idx < len(rollout_levels) - 1:
                    idx += 1
                consecutive_passes = 0
            reason = "promotion_gate_passed" if gate_passed else "promotion_gate_failed"

        rollout_pct = rollout_levels[idx]
        final_ready = bool(rollout_pct == 100 and gate_passed and live_ok)
        mode_state.update(
            {
                "rollout_level_idx": idx,
                "consecutive_passes": consecutive_passes,
                "model_signature": model_signature,
                "current_rollout_pct": rollout_pct,
                "shadow_session_dates": shadow_dates,
                "shadow_sessions": len(shadow_dates),
                "shadow_sessions_required": int(cfg.shadow_sessions_required),
                "last_evaluated_at": datetime.utcnow().isoformat(),
                "last_reason": reason,
                "final_decision_ready": final_ready,
            }
        )
        state["modes"][mode] = mode_state
        rollout_by_mode[mode] = rollout_pct
        final_by_mode[mode] = final_ready
        mode_results[mode] = {
            "status": "ok",
            "reason": reason,
            "rollout_pct": rollout_pct,
            "live_active": rollout_pct > 0,
            "final_decision_ready": final_ready,
            "consecutive_passes": consecutive_passes,
            "model_changed": model_changed,
            "shadow_sessions": len(shadow_dates),
            "shadow_sessions_required": int(cfg.shadow_sessions_required),
            "shadow_sessions_ok": shadow_sessions_ok,
            "model_gate": model_gate,
            "accuracy_gate": accuracy_gate,
            "walk_forward_gate": wf_gate,
            "live_gate": live_gate,
        }

    final_modes = sorted([mode for mode, ready in final_by_mode.items() if ready])
    state["rollout_by_mode"] = rollout_by_mode
    state["current_rollout_pct"] = max(rollout_by_mode.values(), default=0)
    state["last_evaluated_at"] = datetime.utcnow().isoformat()
    reasons = [str(result.get("reason", "")) for result in mode_results.values()]
    if "rollback_triggered" in reasons:
        state["last_reason"] = "rollback_triggered"
    elif "safety_gate_rollback" in reasons:
        state["last_reason"] = "safety_gate_rollback"
    elif "promotion_gate_passed" in reasons:
        state["last_reason"] = "promotion_gate_passed"
    else:
        state["last_reason"] = "promotion_gate_failed"
    state["final_decision_by_mode"] = final_by_mode
    state["final_decision_ready"] = bool(final_modes)
    state["all_modes_final"] = bool(active_modes) and all(final_by_mode.values())
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    primary_mode = active_modes[0] if active_modes else ""
    primary_result = mode_results.get(primary_mode, {})
    return {
        "status": "ok",
        "message": "Evaluated independent Model V2 promotion criteria by mode.",
        "reason": state["last_reason"],
        "rollout_pct": state["current_rollout_pct"],
        "rollout_by_mode": rollout_by_mode,
        "live_active": any(value > 0 for value in rollout_by_mode.values()),
        "final_decision_ready": bool(final_modes),
        "final_decision_modes": final_modes,
        "final_decision_by_mode": final_by_mode,
        "all_modes_final": bool(state["all_modes_final"]),
        "modes": mode_results,
        "consecutive_passes": max(
            [int(result.get("consecutive_passes", 0)) for result in mode_results.values()],
            default=0,
        ),
        "model_changed": any(bool(result.get("model_changed", False)) for result in mode_results.values()),
        "model_gate": primary_result.get("model_gate", {}),
        "accuracy_gate": primary_result.get("accuracy_gate", {}),
        "walk_forward_gate": primary_result.get("walk_forward_gate", {}),
        "live_gate": primary_result.get("live_gate", {}),
    }


def apply_model_v2_rollout_selection(
    filtered_combined: pd.DataFrame,
    settings: Settings,
    promotion_info: dict[str, Any],
    shadow_csv_path: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Apply per-mode rollout with V1 agreement and Bayesian edge filtering."""
    rollout_by_mode = {
        str(mode).lower(): int(value)
        for mode, value in (promotion_info.get("rollout_by_mode", {}) or {}).items()
    }
    default_rollout = 0
    if not rollout_by_mode:
        global_rollout = int(promotion_info.get("rollout_pct", 0) or 0)
        default_rollout = global_rollout
        rollout_by_mode = {
            str(mode).lower(): global_rollout
            for mode in resolve_active_modes(settings)
        }
    rollout_pct = max(rollout_by_mode.values(), default=0)
    if rollout_pct <= 0 or not Path(shadow_csv_path).exists():
        return filtered_combined, filtered_combined.copy().iloc[0:0], {
            "status": "skipped",
            "message": "Rollout is 0% or shadow signals missing.",
            "rollout_pct": rollout_pct,
            "rollout_by_mode": rollout_by_mode,
            "live_active": False,
            "selected_count": 0,
        }

    shadow_df = pd.read_csv(shadow_csv_path)
    if shadow_df.empty:
        return filtered_combined, filtered_combined.copy().iloc[0:0], {
            "status": "skipped",
            "message": "Shadow signals empty.",
            "rollout_pct": rollout_pct,
            "rollout_by_mode": rollout_by_mode,
            "live_active": True,
            "selected_count": 0,
        }

    filtered_combined = filtered_combined.copy()
    filtered_combined["ticker"] = filtered_combined["ticker"].astype(str).str.upper().str.strip()
    filtered_combined["mode"] = filtered_combined["mode"].astype(str).str.lower().str.strip()
    if "source" not in filtered_combined.columns:
        filtered_combined["source"] = "v1"

    max_positions = max(1, int(settings.risk.max_positions))
    shadow_ranked = apply_bayesian_ticker_edge_filter(
        shadow_df,
        settings=settings,
    )
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
    positive_ev = pd.to_numeric(
        shadow_ranked.get(
            "shadow_expected_r",
            pd.Series(float("nan"), index=shadow_ranked.index),
        ),
        errors="coerce",
    ).fillna(float("-inf")).gt(0.0)
    mode_rollout = (
        shadow_ranked.get("mode", pd.Series("", index=shadow_ranked.index))
        .astype(str)
        .str.lower()
        .map(rollout_by_mode)
        .fillna(default_rollout)
        .astype(int)
    )
    agreement_keys = set(
        zip(
            filtered_combined["ticker"].astype(str),
            filtered_combined["mode"].astype(str),
        )
    )
    agreement = pd.Series(
        [
            (str(ticker).upper().strip(), str(mode).lower().strip()) in agreement_keys
            for ticker, mode in zip(
                shadow_ranked.get("ticker", pd.Series("", index=shadow_ranked.index)),
                shadow_ranked.get("mode", pd.Series("", index=shadow_ranked.index)),
            )
        ],
        index=shadow_ranked.index,
        dtype=bool,
    )
    if not bool(settings.model_v2.require_v1_agreement_for_live):
        agreement[:] = True
    meta_ok = (
        shadow_ranked.get(
            "meta_ticker_edge_action",
            pd.Series("watch", index=shadow_ranked.index),
        )
        .astype(str)
        .str.lower()
        .ne("block")
    )
    shadow_ranked["model_v1_agreement"] = agreement
    shadow_ranked = shadow_ranked[
        source_ok
        & recommended
        & positive_ev
        & (mode_rollout > 0)
        & agreement
        & meta_ok
    ].copy()
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
            "rollout_by_mode": rollout_by_mode,
            "live_active": True,
            "v2_slot_count": 0,
            "v1_backfill_count": int(len(v1_fill)),
            "selected_count": int(len(v1_fill)),
        }
    sort_cols = [col for col in ["shadow_expected_r", "shadow_p_win", "score"] if col in shadow_ranked.columns]
    if sort_cols:
        shadow_ranked = shadow_ranked.sort_values(sort_cols, ascending=[False] * len(sort_cols)).copy()

    accepted_parts: list[pd.DataFrame] = []
    for mode, mode_df in shadow_ranked.groupby("mode", dropna=False):
        mode_key = str(mode).lower()
        mode_pct = int(rollout_by_mode.get(mode_key, default_rollout))
        if mode_pct <= 0:
            continue
        mode_slots = max(1, int(math.ceil(max_positions * (float(mode_pct) / 100.0))))
        selected_mode = mode_df.head(mode_slots).copy()
        selected_mode["model_v2_rollout_pct"] = mode_pct
        accepted_parts.append(selected_mode)
    accepted_df = (
        pd.concat(accepted_parts, ignore_index=True, sort=False)
        if accepted_parts
        else shadow_ranked.iloc[0:0].copy()
    )
    if sort_cols and not accepted_df.empty:
        accepted_df = accepted_df.sort_values(sort_cols, ascending=[False] * len(sort_cols))
    accepted_df = accepted_df.head(max_positions).copy()
    accepted_df["source"] = "model_v2"
    accepted_df["model_v2_live_selected"] = True

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
        "message": "Applied independent Model V2 rollout with V1 agreement and Bayesian ticker edge.",
        "rollout_pct": rollout_pct,
        "rollout_by_mode": rollout_by_mode,
        "live_active": True,
        "agreement_required": bool(settings.model_v2.require_v1_agreement_for_live),
        "v2_slot_count": int(len(accepted_df)),
        "v1_backfill_count": int(len(v1_fill)),
        "selected_count": int(len(live_selection)),
    }

