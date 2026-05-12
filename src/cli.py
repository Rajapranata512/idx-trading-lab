from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.backtest import BacktestCosts, pass_live_gate, run_backtest, run_walk_forward, simulate_mode_trades
from src.analytics import generate_swing_audit_report
from src.config import Settings, load_settings
from src.features.compute_features import compute_features
from src.ingest.load_prices import load_prices_csv, load_prices_from_provider
from src.model_v2 import check_promotion_gate, maybe_auto_train_model_v2, run_model_v2_shadow
from src.model_v2.io import load_state, save_state
from src.notify import build_daily_message, send_telegram_message
from src.paper_trading import maybe_generate_paper_fills
from src.report import (
    generate_weekly_kpi_dashboard,
    reconcile_live_signals,
    write_beginner_coaching_note,
    write_signal_snapshot,
)
from src.report.render_report import render_html_report, write_signal_json
from src.risk import maybe_auto_recalibrate_volatility_targets, maybe_auto_update_event_risk
from src.risk.manager import apply_global_position_limit, propose_trade_plan
from src.runtime import (
    active_modes as resolve_active_modes,
    empty_mode_frame,
    inactive_modes as resolve_inactive_modes,
    mode_activation_payload as build_mode_activation_payload,
    supported_modes as get_supported_modes,
    zero_metrics_payload,
)
from src.strategy import rank_all_modes, score_history_modes
from src.universe import maybe_auto_update_universe
from src.utils import JsonRunLogger, atomic_write_json, load_env_file


def _ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _write_json(path: str | Path, payload: dict[str, Any]) -> str:
    return atomic_write_json(path, payload)


def _flatten_payload(payload: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten_payload(value, full_key))
        else:
            out[full_key] = value
    return out


def _extract_live_config_payload(settings: Settings) -> dict[str, Any]:
    return {
        "pipeline": {
            "active_modes": resolve_active_modes(settings),
            "min_live_score_t1": float(settings.pipeline.min_live_score_t1),
            "min_live_score_swing": float(settings.pipeline.min_live_score_swing),
            "min_avg_volume_20d": float(settings.pipeline.min_avg_volume_20d),
            "top_n_combined": int(settings.pipeline.top_n_combined),
        },
        "risk": {
            "risk_per_trade_pct": float(settings.risk.risk_per_trade_pct),
            "max_positions": int(settings.risk.max_positions),
            "max_positions_t1": int(settings.risk.max_positions_t1),
            "max_positions_swing": int(settings.risk.max_positions_swing),
            "daily_loss_stop_r": float(settings.risk.daily_loss_stop_r),
            "max_position_exposure_pct": float(settings.risk.max_position_exposure_pct),
        },
        "regime": {
            "enabled": bool(settings.regime.enabled),
            "min_breadth_ma50_pct": float(settings.regime.min_breadth_ma50_pct),
            "min_breadth_ma20_pct": float(settings.regime.min_breadth_ma20_pct),
            "min_avg_ret20_pct": float(settings.regime.min_avg_ret20_pct),
            "max_median_atr_pct": float(settings.regime.max_median_atr_pct),
        },
        "guardrail": {
            "kill_switch_enabled": bool(settings.guardrail.kill_switch_enabled),
            "rolling_trades": int(settings.guardrail.rolling_trades),
            "min_rolling_trades": int(settings.guardrail.min_rolling_trades),
            "min_rolling_pf": float(settings.guardrail.min_rolling_pf),
            "min_rolling_expectancy": float(settings.guardrail.min_rolling_expectancy),
            "cooldown_days": int(settings.guardrail.cooldown_days),
        },
        "kpi_gates": {
            "gate_b_swing_profit_factor_min": float(settings.kpi_gates.gate_b_swing_profit_factor_min),
            "gate_b_swing_expectancy_min": float(settings.kpi_gates.gate_b_swing_expectancy_min),
            "gate_b_swing_max_dd_pct_max": float(settings.kpi_gates.gate_b_swing_max_dd_pct_max),
        },
        "rollout": {
            "phase": str(settings.rollout.phase),
            "micro_live_multiplier": float(settings.rollout.micro_live_multiplier),
            "allow_scale_up_to_half": bool(settings.rollout.allow_scale_up_to_half),
        },
        "risk_budget": {
            "enabled": bool(settings.risk_budget.enabled),
            "base_risk_budget_pct": float(settings.risk_budget.base_risk_budget_pct),
            "hard_daily_stop_r": float(settings.risk_budget.hard_daily_stop_r),
            "hard_weekly_stop_r": float(settings.risk_budget.hard_weekly_stop_r),
            "sector_exposure_cap_pct": float(settings.risk_budget.sector_exposure_cap_pct),
        },
    }


def _update_live_config_lock(settings: Settings, run_id: str) -> dict[str, Any]:
    lock_path = Path("reports/live_config_lock.json")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.utcnow().isoformat()
    current_payload = _extract_live_config_payload(settings)
    current_flat = _flatten_payload(current_payload)

    if not lock_path.exists():
        payload = {
            "created_at": now_iso,
            "updated_at": now_iso,
            "run_id": run_id,
            "locked_config": current_payload,
            "changes": [],
        }
        _write_json(lock_path, payload)
        return {
            "status": "initialized",
            "path": str(lock_path),
            "changed": False,
            "changed_keys": [],
        }

    previous = json.loads(lock_path.read_text(encoding="utf-8"))
    locked_config = previous.get("locked_config", {})
    prev_flat = _flatten_payload(locked_config) if isinstance(locked_config, dict) else {}
    changed_keys = sorted(
        {
            key
            for key in set(prev_flat.keys()).union(current_flat.keys())
            if prev_flat.get(key) != current_flat.get(key)
        }
    )
    if not changed_keys:
        previous["updated_at"] = now_iso
        previous["run_id"] = run_id
        _write_json(lock_path, previous)
        return {
            "status": "unchanged",
            "path": str(lock_path),
            "changed": False,
            "changed_keys": [],
        }

    history = previous.get("changes", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "changed_at": now_iso,
            "run_id": run_id,
            "changed_keys": changed_keys,
            "old_values": {k: prev_flat.get(k) for k in changed_keys},
            "new_values": {k: current_flat.get(k) for k in changed_keys},
        }
    )
    next_payload = {
        "created_at": previous.get("created_at", now_iso),
        "updated_at": now_iso,
        "run_id": run_id,
        "locked_config": current_payload,
        "changes": history[-200:],
    }
    _write_json(lock_path, next_payload)
    return {
        "status": "changed_logged",
        "path": str(lock_path),
        "changed": True,
        "changed_keys": changed_keys,
    }


def _evaluate_data_quality(settings: Settings, ingest_info: dict[str, Any]) -> dict[str, Any]:
    cfg = settings.kpi_gates
    out_path = Path("reports/data_quality_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prices_path = Path(settings.data.canonical_prices_path)
    payload: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat(),
        "status": "error",
        "pass": False,
        "path": str(prices_path),
        "reason_codes": [],
        "checks": {},
        "thresholds": {
            "max_stale_days": int(cfg.data_quality_max_stale_days),
            "max_missing_rows": int(cfg.data_quality_max_missing_rows),
            "max_duplicate_rows": int(cfg.data_quality_max_duplicate_rows),
            "max_missing_tickers": int(cfg.data_quality_max_missing_tickers),
            "outlier_ret_1d_pct": float(cfg.data_quality_outlier_ret_1d_pct),
            "max_outlier_rows": int(cfg.data_quality_max_outlier_rows),
        },
        "stats": {
            "rows_total": 0,
            "ticker_total": 0,
            "max_data_date": "",
            "stale_days": -1,
            "missing_rows": 0,
            "duplicate_rows": 0,
            "missing_tickers_count": int(ingest_info.get("missing_tickers_count", 0)),
            "outlier_rows": 0,
        },
        "outlier_samples": [],
    }
    if not prices_path.exists():
        payload["reason_codes"] = ["missing_prices_file"]
        payload["message"] = f"Canonical prices file not found: {prices_path}"
        _write_json(out_path, payload)
        return payload

    df = pd.read_csv(prices_path)
    required_cols = ["date", "ticker", "open", "high", "low", "close", "volume"]
    missing_required = [col for col in required_cols if col not in df.columns]
    if missing_required:
        payload["reason_codes"] = ["missing_required_columns"]
        payload["message"] = "Missing columns: " + ", ".join(missing_required)
        _write_json(out_path, payload)
        return payload

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["ticker"] = work["ticker"].astype(str).str.upper().str.strip()
    for col in ["open", "high", "low", "close", "volume"]:
        work[col] = pd.to_numeric(work[col], errors="coerce")

    rows_total = int(len(work))
    ticker_total = int(work["ticker"].nunique()) if rows_total else 0
    max_data_date = work["date"].max() if rows_total else pd.NaT
    stale_days = -1
    if pd.notna(max_data_date):
        stale_days = int((datetime.utcnow().date() - pd.Timestamp(max_data_date).date()).days)

    missing_rows = int(work[["date", "ticker", "close", "volume"]].isna().any(axis=1).sum())
    duplicate_rows = int(work.duplicated(subset=["ticker", "date"]).sum())
    missing_tickers_count = int(ingest_info.get("missing_tickers_count", 0))

    outlier_threshold = float(cfg.data_quality_outlier_ret_1d_pct)
    outlier_rows = 0
    outlier_samples: list[dict[str, Any]] = []
    ret_work = work.dropna(subset=["ticker", "date", "close"]).sort_values(["ticker", "date"]).copy()
    if not ret_work.empty:
        ret_work["ret_1d_pct"] = ret_work.groupby("ticker")["close"].pct_change() * 100.0
        outlier_mask = ret_work["ret_1d_pct"].abs() > outlier_threshold
        outlier_rows = int(outlier_mask.sum())
        if outlier_rows > 0:
            samples = ret_work.loc[outlier_mask, ["date", "ticker", "close", "ret_1d_pct"]].head(10).copy()
            samples["date"] = pd.to_datetime(samples["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            samples["ret_1d_pct"] = pd.to_numeric(samples["ret_1d_pct"], errors="coerce").round(4)
            outlier_samples = samples.to_dict(orient="records")

    checks = {
        "stale_ok": stale_days >= 0 and stale_days <= int(cfg.data_quality_max_stale_days),
        "missing_ok": missing_rows <= int(cfg.data_quality_max_missing_rows),
        "duplicate_ok": duplicate_rows <= int(cfg.data_quality_max_duplicate_rows),
        "missing_tickers_ok": missing_tickers_count <= int(cfg.data_quality_max_missing_tickers),
        "outlier_ok": outlier_rows <= int(cfg.data_quality_max_outlier_rows),
    }

    reason_codes: list[str] = []
    if not checks["stale_ok"]:
        reason_codes.append("stale_data")
    if not checks["missing_ok"]:
        reason_codes.append("missing_values")
    if not checks["duplicate_ok"]:
        reason_codes.append("duplicate_rows")
    if not checks["missing_tickers_ok"]:
        reason_codes.append("missing_tickers")
    if not checks["outlier_ok"]:
        reason_codes.append("outlier_spike")

    pass_quality = bool(all(checks.values()))
    payload.update(
        {
            "status": "pass" if pass_quality else "blocked",
            "pass": pass_quality,
            "reason_codes": reason_codes,
            "checks": checks,
            "stats": {
                "rows_total": rows_total,
                "ticker_total": ticker_total,
                "max_data_date": pd.Timestamp(max_data_date).strftime("%Y-%m-%d") if pd.notna(max_data_date) else "",
                "stale_days": stale_days,
                "missing_rows": missing_rows,
                "duplicate_rows": duplicate_rows,
                "missing_tickers_count": missing_tickers_count,
                "outlier_rows": outlier_rows,
            },
            "outlier_samples": outlier_samples,
            "message": (
                "Data quality checks passed."
                if pass_quality
                else "Data quality gate blocked live execution: " + ", ".join(reason_codes)
            ),
        }
    )
    _write_json(out_path, payload)
    return payload


def _resolve_model_version(settings: Settings) -> str:
    if settings.model_v2.enabled and not settings.model_v2.shadow_mode:
        return "model_v2_live"
    if settings.model_v2.enabled and settings.model_v2.shadow_mode:
        return "model_v1_with_v2_shadow"
    return "model_v1"


def _row_gate_flags(mode: str, backtest_payload: dict[str, Any], quality_ok: bool) -> dict[str, Any]:
    components = backtest_payload.get("gate_components", {}) if isinstance(backtest_payload, dict) else {}
    mode_component = components.get(str(mode), {}) if isinstance(components, dict) else {}
    return {
        "model_gate_ok": bool(mode_component.get("model_gate_ok", False)),
        "regime_ok": bool(mode_component.get("regime_ok", False)),
        "kill_switch_ok": bool(mode_component.get("kill_switch_ok", False)),
        "promotion_gate_ok": bool(mode_component.get("promotion_gate_ok", True)),
        "quality_ok": bool(quality_ok),
        "final_ok": bool(mode_component.get("final_ok", False)) and bool(quality_ok),
    }


def _apply_quality_to_gate(backtest_payload: dict[str, Any], quality_report: dict[str, Any]) -> dict[str, Any]:
    quality_ok = bool(quality_report.get("pass", False))
    gate_components = backtest_payload.get("gate_components", {})
    if not isinstance(gate_components, dict):
        gate_components = {}
    gate_pass = backtest_payload.get("gate_pass", {})
    if not isinstance(gate_pass, dict):
        gate_pass = {}

    final_gate_pass: dict[str, bool] = {}
    for mode in ["t1", "swing"]:
        mode_component = gate_components.get(mode, {})
        if not isinstance(mode_component, dict):
            mode_component = {}
        mode_component["quality_ok"] = quality_ok
        mode_component["final_ok"] = bool(mode_component.get("final_ok", gate_pass.get(mode, False)) and quality_ok)
        gate_components[mode] = mode_component
        final_gate_pass[mode] = bool(mode_component["final_ok"])

    backtest_payload["gate_components"] = gate_components
    backtest_payload["gate_pass"] = final_gate_pass
    backtest_payload["quality"] = {
        "pass": quality_ok,
        "status": str(quality_report.get("status", "")),
        "reason_codes": quality_report.get("reason_codes", []),
        "checks": quality_report.get("checks", {}),
        "stats": quality_report.get("stats", {}),
        "message": quality_report.get("message", ""),
    }
    return backtest_payload


def _rollout_risk_multiplier(settings: Settings) -> float:
    phase = str(settings.rollout.phase or "").strip().lower()
    if phase == "paper":
        return 0.0
    if phase == "micro_live_025":
        return max(0.0, min(1.0, float(settings.rollout.micro_live_multiplier)))
    if phase == "micro_live_050":
        return 0.5
    return 1.0


def _build_risk_budget_payload(settings: Settings, quality_report: dict[str, Any]) -> dict[str, Any]:
    risk_budget_enabled = bool(settings.risk_budget.enabled)
    quality_ok = bool(quality_report.get("pass", False))
    rollout_phase = str(settings.rollout.phase).strip().lower()
    paper_mode = str(settings.paper_trading.mode).strip().lower()

    multiplier = _rollout_risk_multiplier(settings)
    if bool(settings.paper_trading.enabled) and paper_mode == "paper":
        multiplier = 0.0
    effective_budget_pct = float(settings.risk_budget.base_risk_budget_pct) * multiplier if risk_budget_enabled else 100.0
    effective_budget_pct = max(0.0, round(effective_budget_pct, 4))
    effective_risk_per_trade_pct = round(float(settings.risk.risk_per_trade_pct) * (effective_budget_pct / 100.0), 6)

    status = "active"
    if not quality_ok:
        status = "blocked_by_quality"
    elif effective_budget_pct <= 0:
        status = "paper_only"
    elif rollout_phase.startswith("micro_live"):
        status = "micro_live"

    return {
        "enabled": risk_budget_enabled,
        "status": status,
        "rollout_phase": rollout_phase,
        "paper_mode": paper_mode,
        "risk_budget_pct": effective_budget_pct,
        "effective_risk_per_trade_pct": effective_risk_per_trade_pct,
        "hard_daily_stop_r": float(settings.risk_budget.hard_daily_stop_r),
        "hard_weekly_stop_r": float(settings.risk_budget.hard_weekly_stop_r),
        "sector_exposure_cap_pct": float(settings.risk_budget.sector_exposure_cap_pct),
    }


def _append_operator_alert(
    alerts: list[dict[str, str]],
    *,
    severity: str,
    code: str,
    title: str,
    message: str,
) -> None:
    if any(str(alert.get("code", "")) == code for alert in alerts):
        return
    alerts.append(
        {
            "severity": str(severity).strip().lower() or "info",
            "code": code,
            "title": title,
            "message": message,
        }
    )


def _build_operator_alerts(
    settings: Settings,
    ingest_info: dict[str, Any],
    backtest_payload: dict[str, Any],
    quality_report: dict[str, Any],
    shadow_info: dict[str, Any],
    paper_fill_info: dict[str, Any],
    reconciliation_info: dict[str, Any],
    universe_update: dict[str, Any],
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    mode_activation = backtest_payload.get("mode_activation", {}) if isinstance(backtest_payload, dict) else {}
    if not isinstance(mode_activation, dict):
        mode_activation = {}
    active_modes = mode_activation.get("active_modes", resolve_active_modes(settings))
    inactive_modes = mode_activation.get("inactive_modes", resolve_inactive_modes(settings))
    active_modes = [str(mode).strip().lower() for mode in active_modes if str(mode).strip()]
    inactive_modes = [str(mode).strip().lower() for mode in inactive_modes if str(mode).strip()]

    source = str(ingest_info.get("source", "")).strip()
    if "fallback" in source.lower():
        _append_operator_alert(
            alerts,
            severity="warn",
            code="provider_fallback_active",
            title="Fallback data source active",
            message=f"Latest ingest used `{source}`. Validate market data before trusting backtest or live decisions.",
        )

    if inactive_modes:
        _append_operator_alert(
            alerts,
            severity="info",
            code="mode_freeze_active",
            title="Strategy mode freeze active",
            message=(
                f"Active modes: {', '.join(active_modes) or 'none'}. "
                f"Inactive modes: {', '.join(inactive_modes)}."
            ),
        )

    source_status = universe_update.get("source_status", {}) if isinstance(universe_update, dict) else {}
    if isinstance(source_status, dict):
        missing_sources = [name for name, status in source_status.items() if str(status).strip().lower() == "no_url"]
        if missing_sources:
            _append_operator_alert(
                alerts,
                severity="warn",
                code="universe_source_missing",
                title="Universe auto-update not fully configured",
                message="Missing source URL for: " + ", ".join(sorted(missing_sources)),
            )

    quality_stats = quality_report.get("stats", {}) if isinstance(quality_report, dict) else {}
    outlier_rows = int(quality_stats.get("outlier_rows", 0)) if isinstance(quality_stats, dict) else 0
    if outlier_rows > 0:
        _append_operator_alert(
            alerts,
            severity="warn",
            code="quality_outliers_detected",
            title="Price outliers detected",
            message=f"Latest data-quality check found {outlier_rows} outlier row(s). Review anomalous tickers before promotion.",
        )

    swing_train = (
        shadow_info.get("train", {}).get("modes", {}).get("swing", {})
        if isinstance(shadow_info, dict)
        else {}
    )
    if isinstance(swing_train, dict):
        cv_auc = swing_train.get("cv_auc")
        auc_train = swing_train.get("auc_train")
        auc_value = None
        try:
            if cv_auc is not None:
                auc_value = float(cv_auc)
            elif auc_train is not None:
                auc_value = float(auc_train)
        except (TypeError, ValueError):
            auc_value = None
        if auc_value is not None and auc_value < 0.5:
            _append_operator_alert(
                alerts,
                severity="warn",
                code="model_v2_degraded",
                title="Model v2 quality is below baseline",
                message=f"Latest swing validation metric is {auc_value:.4f}, below random baseline.",
            )

    recon_summary = reconciliation_info.get("summary", {}) if isinstance(reconciliation_info, dict) else {}
    recon_counts = recon_summary.get("counts", {}) if isinstance(recon_summary, dict) else {}
    fill_entries_total = int(recon_counts.get("fill_entries_total", 0)) if isinstance(recon_counts, dict) else 0
    if fill_entries_total <= 0:
        _append_operator_alert(
            alerts,
            severity="warn",
            code="no_execution_feedback",
            title="No execution feedback loop yet",
            message="Live reconciliation still has zero fill entries, so closed-loop retraining is not learning from execution.",
        )

    generated_count = int(paper_fill_info.get("generated_count", 0)) if isinstance(paper_fill_info, dict) else 0
    pending_count = int(paper_fill_info.get("pending_count", 0)) if isinstance(paper_fill_info, dict) else 0
    if generated_count > 0:
        _append_operator_alert(
            alerts,
            severity="info",
            code="paper_fills_generated",
            title="Paper feedback loop advanced",
            message=f"Generated {generated_count} new paper fill(s) for closed-loop learning.",
        )
    elif pending_count > 0:
        _append_operator_alert(
            alerts,
            severity="info",
            code="paper_fills_waiting_horizon",
            title="Paper fills waiting for more bars",
            message=f"{pending_count} signal(s) are still waiting for enough future bars to close realistically.",
        )

    swing_audit = backtest_payload.get("swing_audit", {}) if isinstance(backtest_payload, dict) else {}
    weak_spots = swing_audit.get("weak_spots", []) if isinstance(swing_audit, dict) else []
    if isinstance(weak_spots, list) and weak_spots:
        weakest = weak_spots[0]
        if isinstance(weakest, dict):
            _append_operator_alert(
                alerts,
                severity="warn",
                code="swing_edge_instability",
                title="Swing edge is uneven across buckets",
                message=(
                    f"Weakest bucket: {weakest.get('source', 'bucket')}={weakest.get('label', '-')}. "
                    f"Expectancy R {float(weakest.get('expectancy_r', 0.0)):.4f}, "
                    f"PF {float(weakest.get('profit_factor_r', 0.0)):.4f}."
                ),
            )

    return alerts


def _write_n8n_last_summary(
    settings: Settings,
    run_id: str,
    ingest_info: dict[str, Any],
    backtest_payload: dict[str, Any],
    signal_df: pd.DataFrame,
    allowed_modes: list[str],
    quality_report: dict[str, Any],
    risk_budget: dict[str, Any],
    closed_loop_retrain: dict[str, Any],
    shadow_info: dict[str, Any],
    paper_fill_info: dict[str, Any],
    reconciliation_info: dict[str, Any],
    universe_update: dict[str, Any],
) -> dict[str, Any]:
    signal_total = int(len(signal_df))
    quality_ok = bool(quality_report.get("pass", False))
    gate_pass = backtest_payload.get("gate_pass", {}) if isinstance(backtest_payload, dict) else {}
    gate_t1 = bool(gate_pass.get("t1", False)) if isinstance(gate_pass, dict) else False
    gate_swing = bool(gate_pass.get("swing", False)) if isinstance(gate_pass, dict) else False
    mode_activation = backtest_payload.get("mode_activation", {}) if isinstance(backtest_payload, dict) else {}
    if not isinstance(mode_activation, dict):
        mode_activation = build_mode_activation_payload(settings)
    active_modes = mode_activation.get("active_modes", resolve_active_modes(settings))
    active_modes = [str(mode).strip().lower() for mode in active_modes if str(mode).strip()]
    paper_live_mode = "paper" if str(risk_budget.get("status", "")) == "paper_only" else "live"
    if str(risk_budget.get("status", "")).strip() == "micro_live":
        paper_live_mode = "micro_live"

    risk_active = str(risk_budget.get("status", "")) in {"active", "micro_live"}
    trade_ready = bool(signal_total > 0 and allowed_modes and quality_ok and risk_active)

    if trade_ready:
        status = "SUCCESS"
        action = "EXECUTE_MAX_3"
        action_reason = f"{signal_total} signals available with gate and risk-budget pass."
    elif not quality_ok:
        status = "DATA_QUALITY_BLOCKED"
        action = "NO_TRADE"
        action_reason = str(quality_report.get("message", "Data quality check failed."))
    elif not allowed_modes:
        status = "BLOCKED_BY_GATE"
        action = "NO_TRADE"
        action_reason = (
            "Live gate blocked all active modes."
            if not active_modes
            else "Live gate blocked all active modes: " + ", ".join(active_modes)
        )
    elif signal_total <= 0:
        status = "NO_SIGNAL"
        action = "NO_TRADE"
        action_reason = "No executable signal after filtering."
    elif not risk_active:
        status = "PAPER_MODE"
        action = "NO_TRADE"
        action_reason = "Rollout phase or paper mode is active; execution is disabled."
    else:
        status = "NO_TRADE"
        action = "NO_TRADE"
        action_reason = "No execution condition matched."

    max_date = str(ingest_info.get("max_data_date", "")).strip()
    data_age_days = -1
    if max_date:
        try:
            data_age_days = int((datetime.utcnow().date() - pd.Timestamp(max_date).date()).days)
        except Exception:
            data_age_days = -1

    summary_payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "run_id": run_id,
        "decision_version": "v2026.03.roadmap_90d",
        "status": status,
        "action": action,
        "action_reason": action_reason,
        "trade_ready": trade_ready,
        "allowed_modes": allowed_modes,
        "mode_activation": mode_activation,
        "signals_total": signal_total,
        "gate": {
            "t1": gate_t1,
            "swing": gate_swing,
        },
        "data_max_date": max_date,
        "data_age_days": data_age_days,
        "source": str(ingest_info.get("source", "")),
        "paper_live_mode": paper_live_mode,
        "rollout_phase": str(risk_budget.get("rollout_phase", "")),
        "risk_budget_pct": float(risk_budget.get("risk_budget_pct", 0.0)),
        "risk_budget_status": str(risk_budget.get("status", "")),
        "effective_risk_per_trade_pct": float(risk_budget.get("effective_risk_per_trade_pct", 0.0)),
        "hard_daily_stop_r": float(risk_budget.get("hard_daily_stop_r", 0.0)),
        "hard_weekly_stop_r": float(risk_budget.get("hard_weekly_stop_r", 0.0)),
        "closed_loop_retrain_status": str(closed_loop_retrain.get("status", "")),
        "closed_loop_retrain_triggered": bool(closed_loop_retrain.get("triggered", False)),
        "paper_fills": {
            "status": str(paper_fill_info.get("status", "")),
            "generated_count": int(paper_fill_info.get("generated_count", 0)),
            "pending_count": int(paper_fill_info.get("pending_count", 0)),
            "trade_count_total": int(paper_fill_info.get("trade_count_total", 0)),
            "win_rate_pct": float(paper_fill_info.get("win_rate_pct", 0.0)),
            "expectancy_r": float(paper_fill_info.get("expectancy_r", 0.0)),
            "profit_factor_r": float(paper_fill_info.get("profit_factor_r", 0.0)),
        },
        "swing_audit": backtest_payload.get("swing_audit", {}) if isinstance(backtest_payload.get("swing_audit", {}), dict) else {},
        "quality": {
            "status": str(quality_report.get("status", "")),
            "pass": quality_ok,
            "reason_codes": quality_report.get("reason_codes", []),
            "checks": quality_report.get("checks", {}),
            "stats": quality_report.get("stats", {}),
        },
        "operator_alerts": _build_operator_alerts(
            settings=settings,
            ingest_info=ingest_info,
            backtest_payload=backtest_payload,
            quality_report=quality_report,
            shadow_info=shadow_info,
            paper_fill_info=paper_fill_info,
            reconciliation_info=reconciliation_info,
            universe_update=universe_update,
        ),
    }
    summary_path = _write_json("reports/n8n_last_summary.json", summary_payload)
    return {"path": summary_path, "payload": summary_payload}


def _freeze_kpi_baseline_90d(
    run_id: str,
    backtest_payload: dict[str, Any],
    quality_report: dict[str, Any],
) -> dict[str, Any]:
    path = Path("reports/kpi_baseline_90d.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.utcnow().isoformat()

    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(current, dict):
            current["last_seen_run_id"] = run_id
            current["last_seen_at"] = now_iso
            _write_json(path, current)
        return {"status": "existing", "path": str(path)}

    swing_metrics = (
        backtest_payload.get("metrics", {}).get("swing", {})
        if isinstance(backtest_payload.get("metrics", {}), dict)
        else {}
    )
    wf_summary = (
        backtest_payload.get("walk_forward", {}).get("modes", {}).get("swing", {}).get("summary", {})
        if isinstance(backtest_payload.get("walk_forward", {}), dict)
        else {}
    )
    payload = {
        "created_at": now_iso,
        "run_id": run_id,
        "window_days": 90,
        "baseline": {
            "swing_insample": swing_metrics if isinstance(swing_metrics, dict) else {},
            "swing_walk_forward_oos": wf_summary if isinstance(wf_summary, dict) else {},
            "quality_status": str(quality_report.get("status", "")),
            "quality_pass": bool(quality_report.get("pass", False)),
        },
        "notes": "Baseline snapshot frozen for 30-60-90 roadmap tracking.",
    }
    _write_json(path, payload)
    return {"status": "created", "path": str(path)}


def _load_universe(path: str) -> list[str]:
    universe = pd.read_csv(path)
    if "ticker" not in universe.columns:
        raise ValueError("Universe file must contain 'ticker' column")
    return sorted(universe["ticker"].astype(str).str.upper().str.strip().unique().tolist())


def _merge_with_existing_prices(out_path: str, incoming: pd.DataFrame) -> pd.DataFrame:
    path = Path(out_path)
    if not path.exists():
        return incoming.sort_values(["ticker", "date"]).reset_index(drop=True)

    existing = pd.read_csv(path)
    existing["date"] = pd.to_datetime(existing["date"], errors="coerce")
    if "source" not in existing.columns:
        existing["source"] = "existing_csv"
    if "ingested_at" not in existing.columns:
        existing["ingested_at"] = datetime.utcnow().isoformat()
    existing = existing[
        [
            "date",
            "ticker",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
            "ingested_at",
        ]
    ].copy()

    merged = pd.concat([existing, incoming], ignore_index=True, sort=False)
    merged = merged.sort_values(["ticker", "date", "ingested_at"])
    merged = merged.drop_duplicates(subset=["ticker", "date"], keep="last")
    merged = merged.reset_index(drop=True)
    return merged


def ingest_daily(
    settings: Settings,
    start_date: str | None = None,
    end_date: str | None = None,
    merge_existing: bool = True,
) -> dict[str, Any]:
    tickers = _load_universe(settings.data.universe_csv_path)
    prices, source = load_prices_from_provider(
        settings=settings,
        start_date=start_date,
        end_date=end_date,
        tickers=tickers,
    )
    prices = prices[prices["ticker"].isin(tickers)].sort_values(["ticker", "date"]).reset_index(drop=True)
    fetched_tickers = set(prices["ticker"].unique().tolist())
    missing_tickers = sorted(set(tickers) - fetched_tickers)

    out_path = settings.data.canonical_prices_path
    _ensure_parent(out_path)
    to_save = _merge_with_existing_prices(out_path, prices) if merge_existing else prices
    to_save.to_csv(out_path, index=False)
    return {
        "rows": len(to_save),
        "rows_new": len(prices),
        "tickers": int(to_save["ticker"].nunique()) if not to_save.empty else 0,
        "source": source,
        "max_data_date": to_save["date"].max().strftime("%Y-%m-%d") if not to_save.empty else "",
        "min_data_date": to_save["date"].min().strftime("%Y-%m-%d") if not to_save.empty else "",
        "missing_tickers_count": len(missing_tickers),
        "missing_tickers_sample": missing_tickers[:10],
        "out_path": out_path,
    }


def backfill_history(settings: Settings, years: int = 2, end_date: str | None = None) -> dict[str, Any]:
    if years < 1:
        raise ValueError("years must be >= 1")
    end_dt = pd.Timestamp(end_date).date() if end_date else datetime.utcnow().date()
    start_dt = end_dt - timedelta(days=365 * years)
    info = ingest_daily(
        settings=settings,
        start_date=start_dt.isoformat(),
        end_date=end_dt.isoformat(),
        merge_existing=True,
    )
    info["backfill_years"] = years
    info["backfill_start"] = start_dt.isoformat()
    info["backfill_end"] = end_dt.isoformat()
    return info


def compute_features_step(settings: Settings) -> dict[str, Any]:
    prices = load_prices_csv(settings.data.canonical_prices_path, source="canonical_csv")
    feats = compute_features(prices)
    out_path = "data/processed/features.parquet"
    _ensure_parent(out_path)
    feats.to_parquet(out_path, index=False)
    return {"rows": len(feats), "out_path": out_path}


def score_step(settings: Settings) -> dict[str, Any]:
    feats = pd.read_parquet("data/processed/features.parquet")
    mode_activation = build_mode_activation_payload(settings)
    active_modes = mode_activation["active_modes"]
    top_t1_raw, top_swing_raw, _ = rank_all_modes(
        features=feats,
        min_avg_volume_20d=settings.pipeline.min_avg_volume_20d,
        top_n_per_mode=settings.pipeline.top_n_per_mode,
    )
    if "t1" not in active_modes:
        top_t1_raw = empty_mode_frame(top_t1_raw)
    if "swing" not in active_modes:
        top_swing_raw = empty_mode_frame(top_swing_raw)

    plan_t1 = propose_trade_plan(top_t1_raw, settings.risk)
    plan_swing = propose_trade_plan(top_swing_raw, settings.risk)
    lot_size = int(settings.risk.position_lot)
    t1_small_size_pre = int((plan_t1["size"] < lot_size).sum()) if "size" in plan_t1.columns else 0
    swing_small_size_pre = int((plan_swing["size"] < lot_size).sum()) if "size" in plan_swing.columns else 0

    # Live execution guardrails by mode-specific minimum score.
    min_score_t1 = float(settings.pipeline.min_live_score_t1)
    min_score_swing = float(settings.pipeline.min_live_score_swing)
    t1_before_score = int(len(plan_t1))
    swing_before_score = int(len(plan_swing))
    if "score" in plan_t1.columns:
        plan_t1 = plan_t1[plan_t1["score"] >= min_score_t1].copy()
    if "score" in plan_swing.columns:
        plan_swing = plan_swing[plan_swing["score"] >= min_score_swing].copy()
    t1_after_score = int(len(plan_t1))
    swing_after_score = int(len(plan_swing))

    plan_t1, plan_swing, event_risk_info = _apply_event_risk_filter(
        plan_t1=plan_t1,
        plan_swing=plan_swing,
        settings=settings,
    )
    t1_after_event = int(len(plan_t1))
    swing_after_event = int(len(plan_swing))

    combined_before_size = pd.concat([plan_t1, plan_swing], ignore_index=True, sort=False)
    combined_plan = combined_before_size.copy()
    size_removed = 0
    if "size" in combined_plan.columns:
        size_removed = int((combined_plan["size"] < lot_size).sum())
        combined_plan = combined_plan[combined_plan["size"] >= lot_size].copy()
    combined_after_size = int(len(combined_plan))
    combined_plan = combined_plan.sort_values("score", ascending=False).head(
        settings.pipeline.top_n_combined
    ).reset_index(drop=True)
    combined_after_topn = int(len(combined_plan))
    mode_caps = {
        "t1": int(settings.risk.max_positions_t1) if "t1" in active_modes else 0,
        "swing": int(settings.risk.max_positions_swing) if "swing" in active_modes else 0,
    }
    mode_priority = [
        str(m).strip().lower()
        for m in settings.risk.execution_mode_priority
        if str(m).strip() and str(m).strip().lower() in active_modes
    ]
    execution_plan = apply_global_position_limit(
        combined_plan,
        settings.risk.max_positions,
        max_positions_by_mode=mode_caps,
        mode_priority=mode_priority,
    )
    execution_count = int(len(execution_plan))

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    plan_t1.to_csv(reports_dir / "top_t1.csv", index=False)
    plan_swing.to_csv(reports_dir / "top_swing.csv", index=False)
    combined_plan.to_csv(reports_dir / "daily_report.csv", index=False)
    execution_plan.to_csv(reports_dir / "execution_plan.csv", index=False)

    signal_cols = ["ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size", "reason"]
    signal_df = combined_plan[[c for c in signal_cols if c in combined_plan.columns]].copy()
    signal_path = write_signal_json(signal_df, str(reports_dir / "daily_signal.json"))
    signal_funnel = {
        "generated_at": datetime.utcnow().isoformat(),
        "thresholds": {
            "active_modes": active_modes,
            "inactive_modes": mode_activation["inactive_modes"],
            "min_live_score_t1": min_score_t1,
            "min_live_score_swing": min_score_swing,
            "position_lot": lot_size,
            "top_n_combined": int(settings.pipeline.top_n_combined),
            "max_positions": int(settings.risk.max_positions),
            "max_positions_t1": int(settings.risk.max_positions_t1),
            "max_positions_swing": int(settings.risk.max_positions_swing),
            "execution_mode_priority": mode_priority,
        },
        "modes": {
            "t1": {
                "enabled": "t1" in active_modes,
                "rank_candidates": int(len(top_t1_raw)),
                "after_score_filter": t1_after_score,
                "after_event_risk": t1_after_event,
                "small_size_before_filter": t1_small_size_pre,
                "dropped_by_score": max(0, t1_before_score - t1_after_score),
                "dropped_by_event_risk": max(0, t1_after_score - t1_after_event),
            },
            "swing": {
                "enabled": "swing" in active_modes,
                "rank_candidates": int(len(top_swing_raw)),
                "after_score_filter": swing_after_score,
                "after_event_risk": swing_after_event,
                "small_size_before_filter": swing_small_size_pre,
                "dropped_by_score": max(0, swing_before_score - swing_after_score),
                "dropped_by_event_risk": max(0, swing_after_score - swing_after_event),
            },
        },
        "combined": {
            "before_size_filter": int(len(combined_before_size)),
            "dropped_by_size_filter": size_removed,
            "after_size_filter": combined_after_size,
            "after_top_n_combined": combined_after_topn,
            "execution_plan_count": execution_count,
            "signal_count": int(len(signal_df)),
        },
        "event_risk": event_risk_info,
    }
    signal_funnel_path = _write_json(reports_dir / "signal_funnel.json", signal_funnel)
    return {
        "top_t1": plan_t1,
        "top_swing": plan_swing,
        "combined_plan": combined_plan,
        "execution_plan": execution_plan,
        "signal_path": signal_path,
        "signal_funnel": signal_funnel,
        "signal_funnel_path": signal_funnel_path,
        "event_risk": event_risk_info,
        "mode_activation": mode_activation,
    }


def _apply_live_score_filters(scored: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    active_modes = set(resolve_active_modes(settings))
    if not active_modes:
        return scored.iloc[0:0].copy()
    min_score_t1 = float(settings.pipeline.min_live_score_t1)
    min_score_swing = float(settings.pipeline.min_live_score_swing)
    keep_mask = pd.Series([False] * len(scored), index=scored.index)
    if "t1" in active_modes:
        keep_mask = keep_mask | ((scored["mode"] == "t1") & (scored["score"] >= min_score_t1))
    if "swing" in active_modes:
        keep_mask = keep_mask | ((scored["mode"] == "swing") & (scored["score"] >= min_score_swing))
    return scored[keep_mask].copy()


def _load_event_risk_active(settings: Settings, as_of_date: str | None = None) -> pd.DataFrame:
    cfg = settings.pipeline.event_risk
    path = Path(cfg.blacklist_csv_path)
    if not path.exists():
        # Public repo may track a sample file while live file is ignored for daily updates.
        sample_path = path.with_name(f"{path.stem}.sample{path.suffix}")
        if sample_path.exists():
            path = sample_path
        else:
            return pd.DataFrame(columns=["ticker", "status", "reason", "start_date", "end_date", "updated_at"])

    raw = pd.read_csv(path)
    if "ticker" not in raw.columns:
        raise ValueError("Event blacklist file must contain 'ticker' column")

    df = raw.copy()
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["status"] = df.get("status", "").astype(str).str.upper().str.strip()
    df["reason"] = df.get("reason", "").astype(str)
    df["start_date"] = pd.to_datetime(df.get("start_date"), errors="coerce")
    df["end_date"] = pd.to_datetime(df.get("end_date"), errors="coerce")
    df["updated_at"] = pd.to_datetime(df.get("updated_at"), errors="coerce")

    as_of = pd.Timestamp(as_of_date) if as_of_date else pd.Timestamp.now(tz="UTC").tz_localize(None)
    if getattr(as_of, "tzinfo", None) is not None:
        as_of = as_of.tz_convert(None)
    as_of = as_of.normalize()
    statuses = {str(s).upper().strip() for s in cfg.active_statuses}
    status_ok = df["status"].isin(statuses) if statuses else pd.Series([True] * len(df), index=df.index)

    in_window = (
        (df["start_date"].isna() | (df["start_date"] <= as_of))
        & (df["end_date"].isna() | (df["end_date"] >= as_of))
    )

    no_window = df["start_date"].isna() & df["end_date"].isna()
    recency_cutoff = as_of - pd.Timedelta(days=max(0, int(cfg.default_active_days)))
    recent_if_no_window = df["updated_at"].isna() | (df["updated_at"] >= recency_cutoff)
    active = status_ok & ((~no_window & in_window) | (no_window & recent_if_no_window))

    out = df[active].copy()
    if out.empty:
        return out
    out = out.sort_values(["ticker", "status", "updated_at"], ascending=[True, True, False]).reset_index(drop=True)
    return out


def _apply_event_risk_filter(
    plan_t1: pd.DataFrame,
    plan_swing: pd.DataFrame,
    settings: Settings,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    cfg = settings.pipeline.event_risk
    as_of_date = ""
    if not plan_t1.empty and "date" in plan_t1.columns:
        max_dt = pd.to_datetime(plan_t1["date"], errors="coerce").max()
        if pd.notna(max_dt):
            as_of_date = pd.Timestamp(max_dt).strftime("%Y-%m-%d")
    elif not plan_swing.empty and "date" in plan_swing.columns:
        max_dt = pd.to_datetime(plan_swing["date"], errors="coerce").max()
        if pd.notna(max_dt):
            as_of_date = pd.Timestamp(max_dt).strftime("%Y-%m-%d")

    info: dict[str, Any] = {
        "enabled": bool(cfg.enabled),
        "status": "disabled",
        "message": "Event risk filter disabled",
        "path": cfg.blacklist_csv_path,
        "as_of_date": as_of_date,
        "active_events": 0,
        "excluded_count": 0,
        "excluded_tickers": [],
        "excluded_t1": 0,
        "excluded_swing": 0,
    }

    empty_cols = ["ticker", "mode", "score", "reason", "block_status", "block_reason"]
    excluded_all = pd.DataFrame(columns=empty_cols)

    if not cfg.enabled:
        Path("reports").mkdir(parents=True, exist_ok=True)
        excluded_all.to_csv("reports/event_risk_excluded.csv", index=False)
        return plan_t1, plan_swing, info

    try:
        active = _load_event_risk_active(settings=settings, as_of_date=as_of_date or None)
        info["active_events"] = int(len(active))
        if active.empty:
            info["status"] = "ok"
            info["message"] = "No active event-risk entries"
            Path("reports").mkdir(parents=True, exist_ok=True)
            excluded_all.to_csv("reports/event_risk_excluded.csv", index=False)
            return plan_t1, plan_swing, info

        ticker_map = (
            active.groupby("ticker", as_index=False)
            .agg(
                block_status=("status", lambda s: "|".join(sorted({str(x) for x in s if str(x)}))),
                block_reason=("reason", lambda s: " ; ".join([str(x).strip() for x in s if str(x).strip()][:3])),
            )
        )
        banned = set(ticker_map["ticker"].tolist())

        filtered_t1 = plan_t1[~plan_t1["ticker"].isin(banned)].copy()
        filtered_swing = plan_swing[~plan_swing["ticker"].isin(banned)].copy()

        ex_t1 = plan_t1[plan_t1["ticker"].isin(banned)].copy()
        ex_swing = plan_swing[plan_swing["ticker"].isin(banned)].copy()
        if not ex_t1.empty:
            ex_t1 = ex_t1.merge(ticker_map, on="ticker", how="left")
        if not ex_swing.empty:
            ex_swing = ex_swing.merge(ticker_map, on="ticker", how="left")
        excluded_all = pd.concat([ex_t1, ex_swing], ignore_index=True, sort=False)
        excluded_all = excluded_all.sort_values(["score"], ascending=False).reset_index(drop=True) if not excluded_all.empty else excluded_all

        Path("reports").mkdir(parents=True, exist_ok=True)
        active.to_csv("reports/event_risk_active.csv", index=False)
        excluded_all.to_csv("reports/event_risk_excluded.csv", index=False)

        excluded_tickers = sorted(set(excluded_all["ticker"].tolist())) if not excluded_all.empty else []
        info.update(
            {
                "status": "ok",
                "message": "Event-risk filter applied",
                "excluded_count": int(len(excluded_all)),
                "excluded_tickers": excluded_tickers,
                "excluded_t1": int(len(ex_t1)),
                "excluded_swing": int(len(ex_swing)),
            }
        )
        return filtered_t1, filtered_swing, info
    except Exception as exc:
        info["status"] = "error"
        info["message"] = str(exc)
        if cfg.fail_on_error:
            raise
        Path("reports").mkdir(parents=True, exist_ok=True)
        excluded_all.to_csv("reports/event_risk_excluded.csv", index=False)
        return plan_t1, plan_swing, info


def _safe_datetime(value: Any) -> datetime | None:
    if value in (None, "", "NaT"):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts).to_pydatetime()


def _profit_factor_from_returns(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    gross_profit = float(returns[returns > 0].sum())
    gross_loss_abs = float((-returns[returns < 0]).sum())
    if gross_loss_abs <= 1e-12:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss_abs


def _evaluate_market_regime(features: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    regime_cfg = settings.regime
    df = features.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker"]).copy()
    if df.empty:
        return {
            "enabled": bool(regime_cfg.enabled),
            "as_of_date": "",
            "pass": not regime_cfg.enabled,
            "status": "disabled" if not regime_cfg.enabled else "no_data",
            "reason": "Regime disabled" if not regime_cfg.enabled else "No valid feature rows",
            "values": {
                "breadth_ma50_pct": 0.0,
                "breadth_ma20_pct": 0.0,
                "avg_ret20_pct": 0.0,
                "median_atr_pct": 0.0,
                "sample_tickers": 0,
            },
            "thresholds": {
                "min_breadth_ma50_pct": float(regime_cfg.min_breadth_ma50_pct),
                "min_breadth_ma20_pct": float(regime_cfg.min_breadth_ma20_pct),
                "min_avg_ret20_pct": float(regime_cfg.min_avg_ret20_pct),
                "max_median_atr_pct": float(regime_cfg.max_median_atr_pct),
            },
            "checks": {},
        }

    latest_date = pd.Timestamp(df["date"].max())
    latest = df[df["date"] == latest_date].copy()

    ma50_valid = latest.dropna(subset=["close", "ma_50"])
    ma20_valid = latest.dropna(subset=["close", "ma_20"])
    ret20_valid = latest.dropna(subset=["ret_20d"])
    atr_valid = latest.dropna(subset=["atr_pct"])

    breadth_ma50_pct = float((ma50_valid["close"] > ma50_valid["ma_50"]).mean() * 100.0) if len(ma50_valid) else 0.0
    breadth_ma20_pct = float((ma20_valid["close"] > ma20_valid["ma_20"]).mean() * 100.0) if len(ma20_valid) else 0.0
    avg_ret20_pct = float(ret20_valid["ret_20d"].mean() * 100.0) if len(ret20_valid) else 0.0
    median_atr_pct = float(atr_valid["atr_pct"].median()) if len(atr_valid) else 0.0

    checks = {
        "breadth_ma50_ok": breadth_ma50_pct >= float(regime_cfg.min_breadth_ma50_pct),
        "breadth_ma20_ok": breadth_ma20_pct >= float(regime_cfg.min_breadth_ma20_pct),
        "avg_ret20_ok": avg_ret20_pct >= float(regime_cfg.min_avg_ret20_pct),
        "median_atr_ok": median_atr_pct <= float(regime_cfg.max_median_atr_pct),
    }

    if not regime_cfg.enabled:
        regime_pass = True
        status = "disabled"
        reason = "Regime disabled"
    else:
        regime_pass = bool(all(checks.values()))
        status = "risk_on" if regime_pass else "risk_off"
        failed_checks = [k for k, ok in checks.items() if not ok]
        reason = "All regime checks passed" if regime_pass else f"Failed checks: {', '.join(failed_checks)}"

    return {
        "enabled": bool(regime_cfg.enabled),
        "as_of_date": latest_date.strftime("%Y-%m-%d"),
        "pass": regime_pass,
        "status": status,
        "reason": reason,
        "values": {
            "breadth_ma50_pct": breadth_ma50_pct,
            "breadth_ma20_pct": breadth_ma20_pct,
            "avg_ret20_pct": avg_ret20_pct,
            "median_atr_pct": median_atr_pct,
            "sample_tickers": int(latest["ticker"].nunique()),
        },
        "thresholds": {
            "min_breadth_ma50_pct": float(regime_cfg.min_breadth_ma50_pct),
            "min_breadth_ma20_pct": float(regime_cfg.min_breadth_ma20_pct),
            "min_avg_ret20_pct": float(regime_cfg.min_avg_ret20_pct),
            "max_median_atr_pct": float(regime_cfg.max_median_atr_pct),
        },
        "checks": checks,
    }


def _evaluate_kill_switch(scored_live: pd.DataFrame, costs: BacktestCosts, settings: Settings) -> dict[str, Any]:
    cfg = settings.guardrail
    mode_horizon = {"t1": 1, "swing": 10}
    rolling_trades = max(1, int(cfg.rolling_trades))
    min_trades = max(1, int(cfg.min_rolling_trades))
    min_pf = float(cfg.min_rolling_pf)
    min_expectancy = float(cfg.min_rolling_expectancy)

    modes_payload: dict[str, Any] = {}
    triggered_modes: list[str] = []

    for mode, horizon_days in mode_horizon.items():
        trades = simulate_mode_trades(
            scored_features=scored_live,
            mode=mode,
            horizon_days=horizon_days,
            costs=costs,
        )
        recent = trades.tail(rolling_trades).copy()
        returns = recent["return"].astype(float) if "return" in recent.columns else pd.Series(dtype=float)
        trade_count = int(len(recent))

        rolling_pf = _profit_factor_from_returns(returns)
        rolling_expectancy = float(returns.mean()) if trade_count else 0.0

        triggered = False
        reason = "guardrail_disabled"
        if cfg.kill_switch_enabled:
            if trade_count < min_trades:
                reason = "insufficient_recent_trades"
            else:
                pf_fail = rolling_pf < min_pf
                exp_fail = rolling_expectancy < min_expectancy
                triggered = bool(pf_fail or exp_fail)
                if triggered:
                    failed = []
                    if pf_fail:
                        failed.append("rolling_pf")
                    if exp_fail:
                        failed.append("rolling_expectancy")
                    reason = "triggered_by_" + "_and_".join(failed)
                    triggered_modes.append(mode)
                else:
                    reason = "healthy_recent_performance"

        modes_payload[mode] = {
            "trades_recent": trade_count,
            "rolling_window": rolling_trades,
            "rolling_pf": rolling_pf,
            "rolling_expectancy": rolling_expectancy,
            "triggered": triggered,
            "reason": reason,
        }

    return {
        "enabled": bool(cfg.kill_switch_enabled),
        "thresholds": {
            "rolling_trades": rolling_trades,
            "min_rolling_trades": min_trades,
            "min_rolling_pf": min_pf,
            "min_rolling_expectancy": min_expectancy,
            "cooldown_days": int(cfg.cooldown_days),
        },
        "triggered": bool(triggered_modes),
        "triggered_modes": sorted(triggered_modes),
        "modes": modes_payload,
    }


def _apply_kill_switch_cooldown(
    kill_eval: dict[str, Any],
    settings: Settings,
    as_of_date: str | None,
    persist_state: bool = False,
) -> dict[str, Any]:
    state_path = Path("reports/kill_switch_state.json")
    as_of_dt = _safe_datetime(as_of_date) or datetime.utcnow()
    as_of = as_of_dt.date()

    previous: dict[str, Any] = {}
    if state_path.exists():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    prev_active_modes = sorted({str(x) for x in (previous.get("active_modes") or [])})
    prev_until_dt = _safe_datetime(previous.get("cooldown_until"))
    prev_in_cooldown = bool(prev_until_dt and as_of <= prev_until_dt.date() and prev_active_modes)

    enabled = bool(kill_eval.get("enabled", False))
    triggered_modes = sorted({str(x) for x in (kill_eval.get("triggered_modes") or [])})

    status = "disabled"
    cooldown_until: datetime | None = None
    active_modes: list[str] = []
    if not enabled:
        status = "disabled"
    elif triggered_modes:
        status = "triggered"
        cooldown_until = datetime.combine(as_of, datetime.min.time()) + timedelta(days=max(0, int(settings.guardrail.cooldown_days)))
        active_modes = sorted(set(prev_active_modes if prev_in_cooldown else []).union(triggered_modes))
    elif prev_in_cooldown:
        status = "cooldown"
        cooldown_until = prev_until_dt
        active_modes = prev_active_modes
    else:
        status = "clear"

    payload = {
        "enabled": enabled,
        "status": status,
        "as_of_date": as_of.isoformat(),
        "active": bool(active_modes),
        "active_modes": active_modes,
        "triggered_modes_today": triggered_modes,
        "cooldown_until": cooldown_until.strftime("%Y-%m-%d") if cooldown_until else "",
        "state_path": str(state_path),
    }

    if persist_state:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "updated_at": datetime.utcnow().isoformat(),
                    "as_of_date": as_of.isoformat(),
                    "status": status,
                    "active_modes": active_modes,
                    "cooldown_until": payload["cooldown_until"],
                    "triggered_modes_today": triggered_modes,
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )

    return payload


def walk_forward_step(settings: Settings) -> dict[str, Any]:
    feats = pd.read_parquet("data/processed/features.parquet")
    scored = score_history_modes(feats, min_avg_volume_20d=settings.pipeline.min_avg_volume_20d)
    costs = BacktestCosts(
        buy_fee_pct=settings.backtest.buy_fee_pct,
        sell_fee_pct=settings.backtest.sell_fee_pct,
        slippage_pct=settings.backtest.slippage_pct,
    )
    wf = run_walk_forward(
        scored_features=scored,
        costs=costs,
        settings=settings,
        equity_allocation_pct=settings.backtest.equity_allocation_pct,
        train_days=settings.validation.train_days,
        test_days=settings.validation.test_days,
        step_days=settings.validation.step_days,
        min_train_trades=settings.validation.min_train_trades,
        threshold_grid_t1=settings.validation.threshold_grid_t1,
        threshold_grid_swing=settings.validation.threshold_grid_swing,
    )

    out_path = Path("reports/walk_forward_metrics.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.utcnow().isoformat(),
                "walk_forward": wf,
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return wf


def _run_cost_stress_matrix(
    scored_live: pd.DataFrame,
    settings: Settings,
) -> dict[str, Any]:
    base = settings.backtest
    scenario_defs = [
        {"name": "base", "buy_fee_pct": base.buy_fee_pct, "sell_fee_pct": base.sell_fee_pct, "slippage_pct": base.slippage_pct},
        {
            "name": "stress_low",
            "buy_fee_pct": base.buy_fee_pct + 0.05,
            "sell_fee_pct": base.sell_fee_pct + 0.05,
            "slippage_pct": base.slippage_pct + 0.05,
        },
        {
            "name": "stress_medium",
            "buy_fee_pct": base.buy_fee_pct + 0.10,
            "sell_fee_pct": base.sell_fee_pct + 0.10,
            "slippage_pct": base.slippage_pct + 0.10,
        },
        {
            "name": "stress_high",
            "buy_fee_pct": base.buy_fee_pct + 0.20,
            "sell_fee_pct": base.sell_fee_pct + 0.20,
            "slippage_pct": base.slippage_pct + 0.20,
        },
    ]

    scenarios: list[dict[str, Any]] = []
    for sc in scenario_defs:
        costs = BacktestCosts(
            buy_fee_pct=float(sc["buy_fee_pct"]),
            sell_fee_pct=float(sc["sell_fee_pct"]),
            slippage_pct=float(sc["slippage_pct"]),
        )
        metrics = run_backtest(
            scored_live,
            costs=costs,
            equity_allocation_pct=settings.backtest.equity_allocation_pct,
        )
        swing = metrics.get("swing", {}) if isinstance(metrics, dict) else {}
        scenarios.append(
            {
                "scenario": sc["name"],
                "costs": {
                    "buy_fee_pct": float(sc["buy_fee_pct"]),
                    "sell_fee_pct": float(sc["sell_fee_pct"]),
                    "slippage_pct": float(sc["slippage_pct"]),
                },
                "swing": swing if isinstance(swing, dict) else {},
                "t1": metrics.get("t1", {}) if isinstance(metrics, dict) else {},
            }
        )

    swing_pf_values = [_to_float((x.get("swing", {}) if isinstance(x, dict) else {}).get("ProfitFactor"), 0.0) for x in scenarios]
    swing_expectancy_values = [_to_float((x.get("swing", {}) if isinstance(x, dict) else {}).get("Expectancy"), 0.0) for x in scenarios]
    robust = {
        "worst_case_swing_pf": round(min(swing_pf_values), 6) if swing_pf_values else 0.0,
        "worst_case_swing_expectancy": round(min(swing_expectancy_values), 6) if swing_expectancy_values else 0.0,
        "passes_stress_gate": bool(
            swing_pf_values
            and min(swing_pf_values) >= float(settings.kpi_gates.gate_b_swing_profit_factor_min)
            and min(swing_expectancy_values) >= float(settings.kpi_gates.gate_b_swing_expectancy_min)
        ),
    }
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "scenarios": scenarios,
        "robust_summary": robust,
    }


def backtest_step(settings: Settings, persist_guardrail_state: bool = False) -> dict[str, Any]:
    feats = pd.read_parquet("data/processed/features.parquet")
    mode_activation = build_mode_activation_payload(settings)
    active_modes = mode_activation["active_modes"]
    scored_full = score_history_modes(feats, min_avg_volume_20d=settings.pipeline.min_avg_volume_20d)
    scored_full = scored_full[scored_full["mode"].isin(active_modes)].copy()

    # Keep backtest and live policy consistent by applying the same min-score filters.
    scored_live = _apply_live_score_filters(scored_full, settings)

    costs = BacktestCosts(
        buy_fee_pct=settings.backtest.buy_fee_pct,
        sell_fee_pct=settings.backtest.sell_fee_pct,
        slippage_pct=settings.backtest.slippage_pct,
    )
    results = run_backtest(
        scored_live,
        costs=costs,
        equity_allocation_pct=settings.backtest.equity_allocation_pct,
    )
    for mode in get_supported_modes():
        if mode not in results:
            results[mode] = zero_metrics_payload()
    cost_stress_test = _run_cost_stress_matrix(scored_live=scored_live, settings=settings)

    gate_insample = {
        mode: pass_live_gate(
            metrics=metrics,
            profit_factor_min=settings.backtest.profit_factor_min,
            expectancy_min=settings.backtest.expectancy_min,
            max_drawdown_pct_limit=settings.backtest.max_drawdown_pct_limit,
            min_trades=settings.backtest.min_trades_for_promotion,
        )
        for mode, metrics in results.items()
    }

    wf = run_walk_forward(
        scored_features=scored_full,
        costs=costs,
        settings=settings,
        equity_allocation_pct=settings.backtest.equity_allocation_pct,
        train_days=settings.validation.train_days,
        test_days=settings.validation.test_days,
        step_days=settings.validation.step_days,
        min_train_trades=settings.validation.min_train_trades,
        threshold_grid_t1=settings.validation.threshold_grid_t1,
        threshold_grid_swing=settings.validation.threshold_grid_swing,
    )

    wf_modes = wf.get("modes", {})
    if not isinstance(wf_modes, dict):
        wf_modes = {}
    for mode in get_supported_modes():
        if mode not in wf_modes:
            wf_modes[mode] = {
                "summary": zero_metrics_payload(),
                "folds": [],
                "threshold_stats": {},
            }
    wf["modes"] = wf_modes
    wf_summary_t1 = (wf_modes.get("t1", {}) or {}).get("summary", {})
    wf_summary_swing = (wf_modes.get("swing", {}) or {}).get("summary", {})
    wf_n_folds = int(wf.get("n_folds", 0))

    gate_oos = {
        "t1": bool(
            wf_n_folds >= settings.validation.min_folds and
            pass_live_gate(
                metrics=wf_summary_t1,
                profit_factor_min=settings.backtest.profit_factor_min,
                expectancy_min=settings.backtest.expectancy_min,
                max_drawdown_pct_limit=settings.backtest.max_drawdown_pct_limit,
                min_trades=settings.validation.min_oos_trades,
            )
        ),
        "swing": bool(
            wf_n_folds >= settings.validation.min_folds and
            pass_live_gate(
                metrics=wf_summary_swing,
                profit_factor_min=settings.backtest.profit_factor_min,
                expectancy_min=settings.backtest.expectancy_min,
                max_drawdown_pct_limit=settings.backtest.max_drawdown_pct_limit,
                min_trades=settings.validation.min_oos_trades,
            )
        ),
    }

    promotion_gate_cfg = {
        "min_oos_trades": int(settings.validation.min_oos_trades),
        "min_profit_factor": float(settings.backtest.profit_factor_min),
        "min_expectancy": float(settings.backtest.expectancy_min),
        "max_drawdown_pct": float(settings.backtest.max_drawdown_pct_limit),
    }

    model_v2_promotion_modes: dict[str, dict[str, Any]] = {}
    for mode in ["t1", "swing"]:
        mode_payload = wf_modes.get(mode, {})
        folds_payload = mode_payload.get("folds", []) if isinstance(mode_payload, dict) else []
        fold_metrics: list[dict[str, float]] = []
        if isinstance(folds_payload, list):
            for fold in folds_payload:
                if not isinstance(fold, dict):
                    continue
                oos_metrics = fold.get("oos_metrics", {})
                if isinstance(oos_metrics, dict):
                    fold_metrics.append(oos_metrics)
        model_v2_promotion_modes[mode] = check_promotion_gate(fold_metrics=fold_metrics, gate=promotion_gate_cfg)

    gate_promotion = {
        mode: bool(model_v2_promotion_modes.get(mode, {}).get("passed", False))
        for mode in ["t1", "swing"]
    }
    promotion_required = bool(settings.model_v2.enabled and (not settings.model_v2.shadow_mode))

    if settings.validation.use_walk_forward_gate:
        gate_model = {
            mode: bool(gate_insample.get(mode, False) and gate_oos.get(mode, False))
            for mode in ["t1", "swing"]
        }
    else:
        gate_model = gate_insample

    regime = _evaluate_market_regime(feats, settings)
    kill_eval = _evaluate_kill_switch(scored_live, costs=costs, settings=settings)
    kill_state = _apply_kill_switch_cooldown(
        kill_eval=kill_eval,
        settings=settings,
        as_of_date=regime.get("as_of_date"),
        persist_state=persist_guardrail_state,
    )

    kill_active_modes = set(kill_state.get("active_modes") or [])
    gate_components = {}
    gate_final = {}
    for mode in ["t1", "swing"]:
        mode_enabled = mode in active_modes
        model_ok = bool(gate_model.get(mode, False))
        regime_ok = bool(regime.get("pass", False))
        kill_ok = mode not in kill_active_modes
        promotion_ok = bool(gate_promotion.get(mode, False)) if promotion_required else True
        final_ok = bool(mode_enabled and model_ok and regime_ok and kill_ok and promotion_ok)
        gate_components[mode] = {
            "mode_enabled": mode_enabled,
            "model_gate_ok": model_ok,
            "regime_ok": regime_ok,
            "kill_switch_ok": kill_ok,
            "promotion_required": promotion_required,
            "promotion_gate_ok": promotion_ok,
            "final_ok": final_ok,
        }
        gate_final[mode] = final_ok

    swing_audit = generate_swing_audit_report(
        features=feats,
        settings=settings,
        costs=costs,
    )
    out_payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "equity_allocation_pct": settings.backtest.equity_allocation_pct,
        "min_live_score_t1": settings.pipeline.min_live_score_t1,
        "min_live_score_swing": settings.pipeline.min_live_score_swing,
        "mode_activation": mode_activation,
        "validation": {
            "use_walk_forward_gate": settings.validation.use_walk_forward_gate,
            "train_days": settings.validation.train_days,
            "test_days": settings.validation.test_days,
            "step_days": settings.validation.step_days,
            "min_folds": settings.validation.min_folds,
            "min_train_trades": settings.validation.min_train_trades,
            "min_oos_trades": settings.validation.min_oos_trades,
            "active_modes": active_modes,
        },
        "metrics": results,
        "walk_forward": wf,
        "regime": regime,
        "kill_switch_eval": kill_eval,
        "kill_switch": kill_state,
        "gate_pass_insample": gate_insample,
        "gate_pass_oos": gate_oos,
        "gate_pass_promotion": gate_promotion,
        "gate_pass_model": gate_model,
        "gate_components": gate_components,
        "gate_pass": gate_final,
        "model_v2_promotion": {
            "enabled": bool(settings.model_v2.enabled),
            "shadow_mode": bool(settings.model_v2.shadow_mode),
            "required_for_live": promotion_required,
            "gate": promotion_gate_cfg,
            "gate_pass": gate_promotion,
            "modes": model_v2_promotion_modes,
        },
        "cost_stress_test": cost_stress_test,
        "swing_audit": swing_audit,
    }
    _write_json("reports/backtest_metrics.json", out_payload)
    _write_json(
        "reports/walk_forward_metrics.json",
        {
            "generated_at": out_payload["generated_at"],
            "walk_forward": wf,
            "gate_pass_oos": gate_oos,
            "gate_pass_promotion": gate_promotion,
            "gate_pass_model": gate_model,
            "gate_pass": gate_final,
            "model_v2_promotion": out_payload["model_v2_promotion"],
            "mode_activation": mode_activation,
        },
    )
    return out_payload


def send_telegram_step(settings: Settings, run_id: str, data_status: str | None = None) -> bool:
    signal_path = Path("reports/daily_signal.json")
    if not signal_path.exists():
        return False
    payload = json.loads(signal_path.read_text(encoding="utf-8"))
    signals = payload.get("signals", [])
    top = signals[:3]
    top_lines = [
        f"{row.get('mode', '')}:{row.get('ticker', '')} score={row.get('score', '')} entry={row.get('entry', '')} stop={row.get('stop', '')}"
        for row in top
    ]

    risk_summary = (
        f"risk/trade={settings.risk.risk_per_trade_pct}% | "
        f"max_positions={settings.risk.max_positions} | "
        f"mode_caps=t1:{settings.risk.max_positions_t1},swing:{settings.risk.max_positions_swing} | "
        f"daily_loss_stop={settings.risk.daily_loss_stop_r}R"
    )
    status_line = data_status or f"signals={len(signals)}"
    message = build_daily_message(run_id=run_id, top_lines=top_lines, risk_summary=risk_summary, data_status=status_line)
    return send_telegram_message(
        message=message,
        bot_token_env=settings.notifications.telegram_bot_token_env,
        chat_id_env=settings.notifications.telegram_chat_id_env,
    )


def reconcile_live_step(
    settings: Settings,
    fills_path: str | None = None,
    lookback_days: int | None = None,
) -> dict[str, Any]:
    return reconcile_live_signals(
        settings=settings,
        fills_path=fills_path,
        lookback_days=lookback_days,
    )


def paper_fill_step(
    settings: Settings,
    lookback_days: int | None = None,
) -> dict[str, Any]:
    return maybe_generate_paper_fills(
        settings=settings,
        lookback_days=lookback_days,
    )


def swing_audit_step(settings: Settings) -> dict[str, Any]:
    feats = pd.read_parquet("data/processed/features.parquet")
    costs = BacktestCosts(
        buy_fee_pct=settings.backtest.buy_fee_pct,
        sell_fee_pct=settings.backtest.sell_fee_pct,
        slippage_pct=settings.backtest.slippage_pct,
    )
    return generate_swing_audit_report(
        features=feats,
        settings=settings,
        costs=costs,
    )


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _parse_iso_dt(value: Any) -> datetime | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _maybe_trigger_closed_loop_retrain(
    settings: Settings,
    feat_info: dict[str, Any],
    reconciliation_info: dict[str, Any],
) -> dict[str, Any]:
    cfg = settings.model_v2
    now = datetime.utcnow()
    state_path = cfg.closed_loop_state_path
    state = load_state(state_path)

    payload: dict[str, Any] = {
        "status": "skipped_disabled",
        "message": "Closed-loop retrain disabled",
        "enabled": bool(cfg.closed_loop_retrain_enabled),
        "triggered": False,
        "state_path": state_path,
        "fills_csv_path": settings.reconciliation.fills_csv_path,
        "fills_in_window": 0,
        "new_fills_since_last_trigger": 0,
        "live_samples": 0,
        "live_profit_factor_r": 0.0,
        "live_expectancy_r": 0.0,
        "thresholds": {
            "min_live_samples": int(cfg.closed_loop_min_live_samples),
            "min_new_fills": int(cfg.closed_loop_min_new_fills),
            "min_profit_factor_r": float(cfg.closed_loop_min_profit_factor_r),
            "min_expectancy_r": float(cfg.closed_loop_min_expectancy_r),
            "min_hours_between_retrain": int(cfg.closed_loop_min_hours_between_retrain),
        },
        "reasons": [],
        "cooldown_hours_remaining": 0.0,
        "train": {},
    }

    if not cfg.enabled or not cfg.auto_train_enabled or not cfg.closed_loop_retrain_enabled:
        return payload

    summary: dict[str, Any] = {}
    if isinstance(reconciliation_info, dict):
        raw_summary = reconciliation_info.get("summary", {})
        if isinstance(raw_summary, dict):
            summary = raw_summary
    if not summary:
        payload["status"] = "skipped_no_reconciliation_summary"
        payload["message"] = "Reconciliation summary unavailable for closed-loop evaluation"
        save_state(
            state_path,
            {
                **state,
                "last_evaluated_at": now.isoformat(),
                "last_status": payload["status"],
                "last_message": payload["message"],
            },
        )
        return payload

    counts = summary.get("counts", {}) if isinstance(summary.get("counts", {}), dict) else {}
    realized_kpi = summary.get("realized_kpi", {}) if isinstance(summary.get("realized_kpi", {}), dict) else {}

    fills_in_window = max(0, _to_int(counts.get("fill_entries_total", 0), 0))
    live_samples = max(0, _to_int(realized_kpi.get("samples", 0), 0))
    live_pf = _to_float(realized_kpi.get("profit_factor_r", 0.0), 0.0)
    live_expectancy = _to_float(realized_kpi.get("expectancy_r", 0.0), 0.0)

    last_trigger_fills = max(0, _to_int(state.get("last_trigger_fill_entries_total", 0), 0))
    new_fills_since_trigger = max(0, fills_in_window - last_trigger_fills)

    payload["fills_in_window"] = fills_in_window
    payload["new_fills_since_last_trigger"] = new_fills_since_trigger
    payload["live_samples"] = live_samples
    payload["live_profit_factor_r"] = round(float(live_pf), 6)
    payload["live_expectancy_r"] = round(float(live_expectancy), 6)

    min_live_samples = int(cfg.closed_loop_min_live_samples)
    min_new_fills = int(cfg.closed_loop_min_new_fills)
    min_pf = float(cfg.closed_loop_min_profit_factor_r)
    min_expectancy = float(cfg.closed_loop_min_expectancy_r)
    min_hours_between = max(0, int(cfg.closed_loop_min_hours_between_retrain))

    performance_degraded = live_samples >= min_live_samples and (live_pf < min_pf or live_expectancy < min_expectancy)
    fills_ready = new_fills_since_trigger >= min_new_fills

    reasons: list[str] = []
    if performance_degraded:
        reasons.append("performance_degraded")
    if fills_ready:
        reasons.append("new_fills_ready")
    payload["reasons"] = reasons

    last_triggered_at = _parse_iso_dt(state.get("last_triggered_at", ""))
    if last_triggered_at and min_hours_between > 0:
        elapsed_hours = (now - last_triggered_at).total_seconds() / 3600.0
        if elapsed_hours < min_hours_between:
            payload["status"] = "skipped_cooldown"
            payload["message"] = "Closed-loop retrain in cooldown window"
            payload["cooldown_hours_remaining"] = round(float(min_hours_between - elapsed_hours), 2)
            save_state(
                state_path,
                {
                    **state,
                    "last_evaluated_at": now.isoformat(),
                    "last_status": payload["status"],
                    "last_message": payload["message"],
                    "last_seen_fill_entries_total": fills_in_window,
                    "last_live_samples": live_samples,
                    "last_live_profit_factor_r": live_pf,
                    "last_live_expectancy_r": live_expectancy,
                },
            )
            return payload

    if not reasons:
        payload["status"] = "skipped_no_trigger"
        payload["message"] = "Closed-loop conditions not met"
        save_state(
            state_path,
            {
                **state,
                "last_evaluated_at": now.isoformat(),
                "last_status": payload["status"],
                "last_message": payload["message"],
                "last_seen_fill_entries_total": fills_in_window,
                "last_live_samples": live_samples,
                "last_live_profit_factor_r": live_pf,
                "last_live_expectancy_r": live_expectancy,
            },
        )
        return payload

    features_path = str(feat_info.get("out_path", "")).strip()
    if not features_path:
        payload["status"] = "error"
        payload["message"] = "Feature parquet path is empty; cannot retrain"
        save_state(
            state_path,
            {
                **state,
                "last_evaluated_at": now.isoformat(),
                "last_status": payload["status"],
                "last_message": payload["message"],
            },
        )
        return payload

    feature_file = Path(features_path)
    if not feature_file.exists():
        payload["status"] = "error"
        payload["message"] = f"Feature parquet not found: {features_path}"
        save_state(
            state_path,
            {
                **state,
                "last_evaluated_at": now.isoformat(),
                "last_status": payload["status"],
                "last_message": payload["message"],
            },
        )
        return payload

    feats = pd.read_parquet(feature_file)
    scored_history = score_history_modes(
        feats,
        min_avg_volume_20d=settings.pipeline.min_avg_volume_20d,
    )
    train_info = maybe_auto_train_model_v2(
        scored_history=scored_history,
        settings=settings,
        force=True,
    )

    payload["triggered"] = True
    payload["train"] = train_info
    payload["status"] = "triggered" if bool(train_info.get("updated", False)) else "triggered_no_update"
    payload["message"] = (
        "Closed-loop retrain triggered and updated model artifacts"
        if payload["status"] == "triggered"
        else "Closed-loop retrain trigger executed, but no model artifacts were updated"
    )

    save_state(
        state_path,
        {
            **state,
            "last_evaluated_at": now.isoformat(),
            "last_status": payload["status"],
            "last_message": payload["message"],
            "last_seen_fill_entries_total": fills_in_window,
            "last_triggered_at": now.isoformat(),
            "last_trigger_fill_entries_total": fills_in_window,
            "last_trigger_reasons": reasons,
            "last_trigger_train_status": str(train_info.get("status", "")),
            "last_live_samples": live_samples,
            "last_live_profit_factor_r": live_pf,
            "last_live_expectancy_r": live_expectancy,
        },
    )
    return payload


def run_daily(
    settings: Settings,
    skip_telegram: bool = False,
    settings_path: str | Path | None = None,
) -> dict[str, Any]:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = JsonRunLogger(run_id=run_id, out_dir="reports")
    try:
        logger.event("INFO", "start_run", command="run-daily")
        live_config_lock = _update_live_config_lock(settings=settings, run_id=run_id)
        logger.event(
            "INFO",
            "live_config_lock_checked",
            status=live_config_lock.get("status", ""),
            changed=bool(live_config_lock.get("changed", False)),
            changed_keys=live_config_lock.get("changed_keys", []),
            path=live_config_lock.get("path", ""),
        )
        universe_update = maybe_auto_update_universe(settings=settings, force=False)
        logger.event("INFO", "universe_update_done", **universe_update)

        ingest_info = ingest_daily(settings)
        logger.event("INFO", "ingest_done", **ingest_info)
        quality_report = _evaluate_data_quality(settings=settings, ingest_info=ingest_info)
        logger.event(
            "INFO",
            "data_quality_evaluated",
            status=quality_report.get("status", ""),
            quality_pass=bool(quality_report.get("pass", False)),
            reason_codes=quality_report.get("reason_codes", []),
            stats=quality_report.get("stats", {}),
        )

        feat_info = compute_features_step(settings)
        logger.event("INFO", "features_done", **feat_info)

        vol_recalibration = maybe_auto_recalibrate_volatility_targets(
            settings=settings,
            settings_path=settings_path,
            force=False,
            features_path=feat_info["out_path"],
        )
        logger.event("INFO", "volatility_recalibration_done", **vol_recalibration)

        event_risk_update = maybe_auto_update_event_risk(settings=settings, force=False)
        logger.event("INFO", "event_risk_update_done", **event_risk_update)

        score_info = score_step(settings)
        top_t1: pd.DataFrame = score_info["top_t1"]
        top_swing: pd.DataFrame = score_info["top_swing"]
        event_risk_info = score_info.get("event_risk", {})
        logger.event("INFO", "event_risk_filtered", **event_risk_info)

        shadow_info: dict[str, Any] = {
            "status": "disabled",
            "message": "Model v2 shadow mode disabled",
        }
        if settings.model_v2.enabled and settings.model_v2.shadow_mode:
            try:
                feats_for_shadow = pd.read_parquet(feat_info["out_path"])
                scored_hist_shadow = score_history_modes(
                    feats_for_shadow,
                    min_avg_volume_20d=settings.pipeline.min_avg_volume_20d,
                )
                shadow_info = run_model_v2_shadow(
                    settings=settings,
                    scored_history=scored_hist_shadow,
                    candidates=score_info.get("combined_plan", pd.DataFrame()),
                    run_id=run_id,
                )
                logger.event("INFO", "model_v2_shadow_done", **shadow_info)
            except Exception as exc:
                shadow_info = {
                    "status": "error",
                    "message": str(exc),
                }
                logger.event("WARN", "model_v2_shadow_failed", error=str(exc))

        risk_summary = {
            "risk_per_trade_pct": settings.risk.risk_per_trade_pct,
            "max_positions": settings.risk.max_positions,
            "max_positions_t1": settings.risk.max_positions_t1,
            "max_positions_swing": settings.risk.max_positions_swing,
            "execution_mode_priority": settings.risk.execution_mode_priority,
            "daily_loss_stop_r": settings.risk.daily_loss_stop_r,
            "vol_target_enabled": settings.risk.volatility_targeting_enabled,
            "vol_target_ref_atr_pct": settings.risk.volatility_reference_atr_pct,
            "vol_target_ref_realized_pct": settings.risk.volatility_reference_realized_pct,
            "vol_target_mode": settings.risk.volatility_targeting_mode,
            "vol_target_realized_weight": settings.risk.volatility_realized_weight,
            "vol_target_cap_base": settings.risk.volatility_cap_multiplier,
            "vol_target_regime_cap_enabled": settings.risk.volatility_market_regime_cap_enabled,
            "vol_target_regime_cap_high": settings.risk.volatility_market_regime_high_max_mult,
            "vol_target_regime_cap_stress": settings.risk.volatility_market_regime_stress_max_mult,
            "max_position_exposure_pct": settings.risk.max_position_exposure_pct,
        }
        report_path = render_html_report(
            top_t1=top_t1,
            top_swing=top_swing,
            out_path="reports/daily_report.html",
            run_id=run_id,
            data_source=ingest_info["source"],
            max_data_date=ingest_info["max_data_date"],
            universe_name="LQ45+IDX30",
            risk_summary=risk_summary,
        )
        logger.event("INFO", "report_done", report_path=report_path, signal_path=score_info["signal_path"])

        bt = backtest_step(settings, persist_guardrail_state=True)
        bt = _apply_quality_to_gate(backtest_payload=bt, quality_report=quality_report)
        _write_json("reports/backtest_metrics.json", bt)
        logger.event(
            "INFO",
            "backtest_done",
            metrics=bt.get("metrics", {}),
            gate_pass=bt.get("gate_pass", {}),
            gate_pass_promotion=bt.get("gate_pass_promotion", {}),
            regime=bt.get("regime", {}),
            kill_switch=bt.get("kill_switch", {}),
            model_v2_promotion=bt.get("model_v2_promotion", {}),
            quality=bt.get("quality", {}),
            cost_stress=bt.get("cost_stress_test", {}).get("robust_summary", {}),
        )

        gate_pass = bt.get("gate_pass", {})
        mode_activation = bt.get("mode_activation", {}) if isinstance(bt, dict) else {}
        active_mode_order = mode_activation.get("active_modes", resolve_active_modes(settings)) if isinstance(mode_activation, dict) else resolve_active_modes(settings)
        allowed_mode_set = {str(mode).strip().lower() for mode, ok in gate_pass.items() if bool(ok)}
        allowed_modes = [mode for mode in active_mode_order if mode in allowed_mode_set]
        filtered_combined = pd.DataFrame()
        filtered_execution = pd.DataFrame()
        signal_df = pd.DataFrame(columns=["ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size", "reason"])
        model_version = _resolve_model_version(settings)
        quality_ok = bool(quality_report.get("pass", False))
        if not allowed_modes:
            empty_signals = pd.DataFrame(
                columns=["ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size", "reason"]
            )
            write_signal_json(
                empty_signals,
                "reports/daily_signal.json",
                model_version=model_version,
                default_gate_flags={
                    "quality_ok": quality_ok,
                    "final_ok": False,
                },
            )
            pd.DataFrame(columns=empty_signals.columns).to_csv("reports/execution_plan.csv", index=False)
            logger.event(
                "WARN",
                "live_gate_blocked",
                gate_pass=gate_pass,
                gate_components=bt.get("gate_components", {}),
                gate_pass_promotion=bt.get("gate_pass_promotion", {}),
                model_v2_promotion=bt.get("model_v2_promotion", {}),
                regime=bt.get("regime", {}),
                kill_switch=bt.get("kill_switch", {}),
            )
        else:
            combined_plan: pd.DataFrame = score_info["combined_plan"]
            execution_plan: pd.DataFrame = score_info["execution_plan"]

            filtered_combined = combined_plan[combined_plan["mode"].isin(allowed_modes)].copy()
            filtered_execution = execution_plan[execution_plan["mode"].isin(allowed_modes)].copy()
            filtered_combined.to_csv("reports/daily_report.csv", index=False)
            filtered_execution.to_csv("reports/execution_plan.csv", index=False)

            signal_cols = ["ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size", "reason"]
            signal_df = filtered_combined[[c for c in signal_cols if c in filtered_combined.columns]].copy()
            if not signal_df.empty:
                signal_df["gate_flags"] = signal_df["mode"].astype(str).str.lower().apply(
                    lambda mode: _row_gate_flags(mode=mode, backtest_payload=bt, quality_ok=quality_ok)
                )
                signal_df["model_version"] = model_version
            write_signal_json(
                signal_df,
                "reports/daily_signal.json",
                model_version=model_version,
                default_gate_flags={
                    "quality_ok": quality_ok,
                },
            )
            logger.event(
                "INFO",
                "live_gate_modes_allowed",
                allowed_modes=allowed_modes,
                signal_count=int(len(signal_df)),
            )

        snapshot_info: dict[str, Any] = {"status": "ok", "path": "", "signal_count": int(len(signal_df))}
        try:
            snapshot_path = write_signal_snapshot(
                run_id=run_id,
                signals=signal_df,
                out_dir=settings.reconciliation.signal_snapshot_dir,
            )
            snapshot_info["path"] = snapshot_path
            logger.event("INFO", "signal_snapshot_written", path=snapshot_path, signal_count=int(len(signal_df)))
        except Exception as exc:
            snapshot_info = {"status": "error", "path": "", "signal_count": int(len(signal_df)), "message": str(exc)}
            logger.event("WARN", "signal_snapshot_failed", error=str(exc))
            if settings.reconciliation.fail_on_error:
                raise

        reconciliation_info: dict[str, Any] = {
            "status": "disabled",
            "message": "Live reconciliation disabled",
        }
        paper_fill_info: dict[str, Any] = {
            "status": "disabled",
            "message": "Paper fill generation disabled",
        }
        try:
            paper_fill_info = paper_fill_step(settings=settings)
            logger.event(
                "INFO",
                "paper_fill_generation_done",
                status=paper_fill_info.get("status", ""),
                generated_count=int(paper_fill_info.get("generated_count", 0)),
                pending_count=int(paper_fill_info.get("pending_count", 0)),
                trade_count_total=int(paper_fill_info.get("trade_count_total", 0)),
            )
        except Exception as exc:
            paper_fill_info = {"status": "error", "message": str(exc)}
            logger.event("WARN", "paper_fill_generation_failed", error=str(exc))
        if settings.reconciliation.enabled and settings.reconciliation.auto_reconcile_on_run_daily:
            try:
                reconciliation_info = reconcile_live_step(settings=settings)
                logger.event(
                    "INFO",
                    "live_reconciliation_done",
                    status=reconciliation_info.get("status", ""),
                    message=reconciliation_info.get("message", ""),
                    json_path=reconciliation_info.get("json_path", ""),
                    details_csv_path=reconciliation_info.get("details_csv_path", ""),
                )
            except Exception as exc:
                reconciliation_info = {"status": "error", "message": str(exc)}
                logger.event("WARN", "live_reconciliation_failed", error=str(exc))
                if settings.reconciliation.fail_on_error:
                    raise
        elif settings.reconciliation.enabled:
            reconciliation_info = {
                "status": "skipped_auto_disabled",
                "message": "Auto reconciliation on run-daily disabled",
            }

        closed_loop_retrain: dict[str, Any] = {
            "status": "skipped_disabled",
            "message": "Closed-loop retrain disabled",
            "triggered": False,
        }
        try:
            closed_loop_retrain = _maybe_trigger_closed_loop_retrain(
                settings=settings,
                feat_info=feat_info,
                reconciliation_info=reconciliation_info,
            )
            logger.event(
                "INFO",
                "closed_loop_retrain_evaluated",
                status=closed_loop_retrain.get("status", ""),
                triggered=bool(closed_loop_retrain.get("triggered", False)),
                fills_in_window=int(closed_loop_retrain.get("fills_in_window", 0)),
                new_fills_since_last_trigger=int(closed_loop_retrain.get("new_fills_since_last_trigger", 0)),
                live_samples=int(closed_loop_retrain.get("live_samples", 0)),
                reasons=closed_loop_retrain.get("reasons", []),
                train_status=closed_loop_retrain.get("train", {}).get("status", ""),
            )
        except Exception as exc:
            closed_loop_retrain = {
                "status": "error",
                "message": str(exc),
                "triggered": False,
            }
            logger.event("WARN", "closed_loop_retrain_failed", error=str(exc))

        risk_budget_info = _build_risk_budget_payload(settings=settings, quality_report=quality_report)
        logger.event(
            "INFO",
            "risk_budget_evaluated",
            status=risk_budget_info.get("status", ""),
            risk_budget_pct=float(risk_budget_info.get("risk_budget_pct", 0.0)),
            effective_risk_per_trade_pct=float(risk_budget_info.get("effective_risk_per_trade_pct", 0.0)),
            rollout_phase=risk_budget_info.get("rollout_phase", ""),
            paper_mode=risk_budget_info.get("paper_mode", ""),
        )

        n8n_summary_info = _write_n8n_last_summary(
            settings=settings,
            run_id=run_id,
            ingest_info=ingest_info,
            backtest_payload=bt,
            signal_df=signal_df,
            allowed_modes=allowed_modes,
            quality_report=quality_report,
            risk_budget=risk_budget_info,
            closed_loop_retrain=closed_loop_retrain,
            shadow_info=shadow_info,
            paper_fill_info=paper_fill_info,
            reconciliation_info=reconciliation_info,
            universe_update=universe_update,
        )
        logger.event(
            "INFO",
            "n8n_summary_written",
            path=n8n_summary_info.get("path", ""),
            status=n8n_summary_info.get("payload", {}).get("status", ""),
            action=n8n_summary_info.get("payload", {}).get("action", ""),
            trade_ready=bool(n8n_summary_info.get("payload", {}).get("trade_ready", False)),
        )

        pre_gate_df: pd.DataFrame = score_info.get("combined_plan", pd.DataFrame())
        post_gate_df: pd.DataFrame = filtered_combined
        pre_by_mode: dict[str, int] = {}
        post_by_mode: dict[str, int] = {}
        if not pre_gate_df.empty and "mode" in pre_gate_df.columns:
            pre_by_mode = {str(k): int(v) for k, v in pre_gate_df["mode"].value_counts().to_dict().items()}
        if not post_gate_df.empty and "mode" in post_gate_df.columns:
            post_by_mode = {str(k): int(v) for k, v in post_gate_df["mode"].value_counts().to_dict().items()}

        live_funnel_payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "run_id": run_id,
            "gate_pass": gate_pass,
            "allowed_modes": allowed_modes,
            "mode_activation": mode_activation,
            "pre_gate": {
                "combined_plan_count": int(len(pre_gate_df)),
                "execution_plan_count": int(len(score_info.get("execution_plan", pd.DataFrame()))),
                "signal_count": int(len(pre_gate_df)),
                "by_mode": pre_by_mode,
            },
            "post_gate": {
                "combined_plan_count": int(len(filtered_combined)),
                "execution_plan_count": int(len(filtered_execution)),
                "signal_count": int(len(signal_df)),
                "by_mode": post_by_mode,
            },
            "status": {
                "regime": bt.get("regime", {}).get("status", ""),
                "kill_switch": bt.get("kill_switch", {}).get("status", ""),
            },
        }
        if "signal_funnel" in score_info:
            live_funnel_payload["score_funnel"] = score_info["signal_funnel"]
        live_funnel_path = _write_json("reports/signal_funnel_live.json", live_funnel_payload)
        logger.event("INFO", "signal_funnel_written", path=live_funnel_path, post_gate_signals=int(len(signal_df)))

        telegram_ok: bool | None = None
        if not skip_telegram:
            signal_count = 0
            signal_path = Path("reports/daily_signal.json")
            if signal_path.exists():
                payload = json.loads(signal_path.read_text(encoding="utf-8"))
                signal_count = len(payload.get("signals", []))
            status = (
                f"source={ingest_info['source']} | max_date={ingest_info['max_data_date']} "
                f"| signals={signal_count} | regime={bt.get('regime', {}).get('status', '-')} "
                f"| kill={bt.get('kill_switch', {}).get('status', '-')} "
                f"| vol_recalib={vol_recalibration.get('status', '-')} "
                f"| event_upd={event_risk_update.get('status', '-')} "
                f"| event_excl={event_risk_info.get('excluded_count', 0)}"
            )
            telegram_ok = send_telegram_step(settings, run_id=run_id, data_status=status)
            logger.event("INFO", "telegram_done", ok=telegram_ok)
        else:
            logger.event("INFO", "telegram_skipped", ok=None)

        weekly_kpi_info: dict[str, Any] = {"status": "disabled", "message": "Coaching features disabled"}
        beginner_note_path = ""
        if settings.coaching.enabled:
            try:
                weekly_kpi_info = generate_weekly_kpi_dashboard(settings=settings)
                logger.event(
                    "INFO",
                    "weekly_kpi_generated",
                    status=weekly_kpi_info.get("status", ""),
                    json_path=weekly_kpi_info.get("json_path", ""),
                )
            except Exception as exc:
                weekly_kpi_info = {"status": "error", "message": str(exc)}
                logger.event("WARN", "weekly_kpi_failed", error=str(exc))

            try:
                beginner_status = "SUCCESS" if len(signal_df) > 0 else "NO_TRADE"
                action_reason = (
                    "Live gate allowed at least one mode and produced actionable signal."
                    if beginner_status == "SUCCESS"
                    else "No live-eligible signal after guardrails or score filters."
                )
                beginner_note_path = write_beginner_coaching_note(
                    out_path=settings.coaching.beginner_note_path,
                    run_id=run_id,
                    status=beginner_status,
                    action_reason=action_reason,
                    signals=signal_df,
                )
                logger.event("INFO", "beginner_coaching_written", path=beginner_note_path)
            except Exception as exc:
                logger.event("WARN", "beginner_coaching_failed", error=str(exc))

        baseline_info = _freeze_kpi_baseline_90d(
            run_id=run_id,
            backtest_payload=bt,
            quality_report=quality_report,
        )
        logger.event(
            "INFO",
            "kpi_baseline_90d_updated",
            status=baseline_info.get("status", ""),
            path=baseline_info.get("path", ""),
        )

        return {
            "run_id": run_id,
            "report_path": report_path,
            "signal_path": score_info["signal_path"],
            "telegram_ok": telegram_ok,
            "backtest": bt,
            "model_v2_shadow": shadow_info,
            "event_risk": event_risk_info,
            "event_risk_update": event_risk_update,
            "signal_snapshot": snapshot_info,
            "paper_fills": paper_fill_info,
            "live_reconciliation": reconciliation_info,
            "closed_loop_retrain": closed_loop_retrain,
            "weekly_kpi": weekly_kpi_info,
            "beginner_note_path": beginner_note_path,
            "volatility_recalibration": vol_recalibration,
            "universe_update": universe_update,
            "data_quality": quality_report,
            "risk_budget": risk_budget_info,
            "paper_live_mode": n8n_summary_info.get("payload", {}).get("paper_live_mode", ""),
            "n8n_summary_path": n8n_summary_info.get("path", ""),
            "kpi_baseline_90d": baseline_info,
            "live_config_lock": live_config_lock,
        }
    except Exception as exc:
        logger.event("ERROR", "run_failed", error=str(exc))
        raise
    finally:
        log_path = logger.save()
        print(f"[run-log] {log_path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IDX Trading Lab CLI")
    parser.add_argument("--settings", default="config/settings.json", help="Path to runtime settings JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest-daily", help="Ingest daily prices from provider")
    p_ingest.add_argument("--start-date", default=None)
    p_ingest.add_argument("--end-date", default=None)
    p_ingest.add_argument("--no-merge", action="store_true")

    p_backfill = sub.add_parser("backfill-history", help="Backfill 1-2+ years historical prices")
    p_backfill.add_argument("--years", type=int, default=2)
    p_backfill.add_argument("--end-date", default=None)

    p_intraday_ingest = sub.add_parser("ingest-intraday", help="Ingest intraday bars from provider")
    p_intraday_ingest.add_argument("--timeframe", default=None, help="Bar timeframe such as 1m/5m/15m")
    p_intraday_ingest.add_argument("--lookback-minutes", type=int, default=None)
    p_intraday_ingest.add_argument("--no-merge", action="store_true")

    p_intraday_run = sub.add_parser("run-intraday", help="Run one intraday cycle: ingest -> features -> score")
    p_intraday_run.add_argument("--lookback-minutes", type=int, default=None)

    p_intraday_daemon = sub.add_parser("run-intraday-daemon", help="Run intraday daemon loop with reconnect/backoff")
    p_intraday_daemon.add_argument("--max-loops", type=int, default=0, help="0 means run forever")

    p_uni = sub.add_parser("update-universe", help="Update LQ45/IDX30 universe using configured sources")
    p_uni.add_argument("--force", action="store_true", help="Ignore interval and force update attempt")
    p_event = sub.add_parser("update-event-risk", help="Update event-risk blacklist using configured sources")
    p_event.add_argument("--force", action="store_true", help="Ignore interval and force update attempt")
    p_recal = sub.add_parser(
        "recalibrate-volatility",
        help="Auto-recalibrate volatility reference targets using recent feature history",
    )
    p_recal.add_argument("--force", action="store_true", help="Ignore interval and force recalibration attempt")
    p_recon = sub.add_parser("reconcile-live", help="Reconcile live fills vs signal snapshots and generate KPI report")
    p_recon.add_argument("--fills-path", default=None, help="Override fills CSV path")
    p_recon.add_argument("--lookback-days", type=int, default=None, help="Override reconciliation lookback window")
    p_paper = sub.add_parser("paper-fills", help="Generate realistic paper fills from historical signal snapshots")
    p_paper.add_argument("--lookback-days", type=int, default=None, help="Override paper-fill lookback window")
    sub.add_parser("weekly-kpi", help="Generate weekly KPI dashboard markdown/json")

    sub.add_parser("compute-features", help="Compute features and save parquet")
    sub.add_parser("score", help="Score T+1 and Swing picks, write reports/daily_signal.json")
    sub.add_parser("backtest", help="Run bar-based backtest on scored history")
    sub.add_parser("walk-forward", help="Run walk-forward out-of-sample validation")
    sub.add_parser("swing-audit", help="Generate swing edge audit by regime, group, and volatility")

    p_notify = sub.add_parser("send-telegram", help="Send Telegram summary")
    p_notify.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))

    p_run = sub.add_parser("run-daily", help="Execute full daily pipeline")
    p_run.add_argument("--skip-telegram", action="store_true")

    p_web = sub.add_parser("serve-web", help="Run interactive web dashboard")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8080)
    p_web.add_argument("--reports-dir", default="reports")
    p_web.add_argument("--static-dir", default="")
    p_web.add_argument("--open-browser", action="store_true")

    return parser


def main() -> None:
    load_env_file()
    parser = _build_parser()
    args = parser.parse_args()
    settings = load_settings(args.settings)

    if args.command == "ingest-daily":
        out = ingest_daily(
            settings,
            start_date=args.start_date,
            end_date=args.end_date,
            merge_existing=not args.no_merge,
        )
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "backfill-history":
        out = backfill_history(settings, years=args.years, end_date=args.end_date)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "ingest-intraday":
        from src.intraday import ingest_intraday_step

        out = ingest_intraday_step(
            settings=settings,
            timeframe=args.timeframe,
            lookback_minutes=args.lookback_minutes,
            merge_existing=not args.no_merge,
        )
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "run-intraday":
        from src.intraday import run_intraday_once

        out = run_intraday_once(settings=settings, lookback_minutes=args.lookback_minutes)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "run-intraday-daemon":
        from src.intraday.daemon import run_intraday_daemon

        run_intraday_daemon(settings_path=args.settings, max_loops=args.max_loops)
        print(json.dumps({"status": "stopped", "max_loops": args.max_loops}, ensure_ascii=True, indent=2))
        return
    if args.command == "update-universe":
        out = maybe_auto_update_universe(settings=settings, force=args.force)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "update-event-risk":
        out = maybe_auto_update_event_risk(settings=settings, force=args.force)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "recalibrate-volatility":
        out = maybe_auto_recalibrate_volatility_targets(settings=settings, settings_path=args.settings, force=args.force)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "paper-fills":
        out = paper_fill_step(settings=settings, lookback_days=args.lookback_days)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "compute-features":
        out = compute_features_step(settings)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "score":
        out = score_step(settings)
        print(json.dumps({"signal_path": out["signal_path"]}, ensure_ascii=True, indent=2))
        return
    if args.command == "backtest":
        out = backtest_step(settings)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "walk-forward":
        out = walk_forward_step(settings)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "swing-audit":
        out = swing_audit_step(settings)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "send-telegram":
        ok = send_telegram_step(settings, run_id=args.run_id)
        print(json.dumps({"ok": ok}, ensure_ascii=True, indent=2))
        return
    if args.command == "run-daily":
        out = run_daily(settings, skip_telegram=args.skip_telegram, settings_path=args.settings)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "serve-web":
        from src.web.server import start_web_server

        start_web_server(
            host=args.host,
            port=args.port,
            settings_path=args.settings,
            reports_dir=args.reports_dir,
            static_dir=(args.static_dir or None),
            open_browser=args.open_browser,
        )
        return

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
 