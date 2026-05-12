from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings
from src.utils import atomic_write_json, atomic_write_text


def _safe_load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _collect_recent_events(reports_dir: Path, lookback_days: int) -> list[dict[str, Any]]:
    cutoff = datetime.utcnow() - timedelta(days=max(1, int(lookback_days)))
    events: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("run_log_*.json")):
        payload = _safe_load_json(path)
        if not isinstance(payload, list):
            continue
        for ev in payload:
            ts_raw = str(ev.get("ts", "")).strip()
            try:
                ts = datetime.fromisoformat(ts_raw)
            except Exception:
                continue
            if ts >= cutoff:
                events.append(ev)
    return events


def _weekly_kpi_payload(settings: Settings, events: list[dict[str, Any]]) -> dict[str, Any]:
    by_run: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        run_id = str(ev.get("run_id", "")).strip()
        if not run_id:
            continue
        by_run.setdefault(run_id, []).append(ev)

    run_count = len(by_run)
    failed_runs = 0
    success_with_trade_modes = 0
    risk_blocked_runs = 0
    setup_errors = 0
    event_updates_ok = 0
    event_updates_error = 0

    for run_id, rows in by_run.items():
        has_error = any(str(r.get("level", "")).upper() == "ERROR" for r in rows)
        if has_error:
            failed_runs += 1
        if any(str(r.get("message", "")) == "live_gate_modes_allowed" for r in rows):
            success_with_trade_modes += 1
        if any(str(r.get("message", "")) == "live_gate_blocked" for r in rows):
            risk_blocked_runs += 1
        if any(str(r.get("message", "")) == "run_failed" for r in rows):
            setup_errors += 1

        for r in rows:
            if str(r.get("message", "")) != "event_risk_update_done":
                continue
            extra = r.get("extra", {}) or {}
            status = str(extra.get("status", "")).strip().lower()
            if status == "error":
                event_updates_error += 1
            elif status:
                event_updates_ok += 1

    error_rate_pct = (failed_runs / run_count * 100.0) if run_count else 0.0

    bt_path = Path("reports/backtest_metrics.json")
    bt = _safe_load_json(bt_path)
    swing = ((bt or {}).get("metrics", {}) or {}).get("swing", {}) if isinstance(bt, dict) else {}
    recon_path = Path(settings.reconciliation.output_json_path)
    recon = _safe_load_json(recon_path)
    recon_coverage = (recon or {}).get("coverage", {}) if isinstance(recon, dict) else {}
    recon_realized = (recon or {}).get("realized_kpi", {}) if isinstance(recon, dict) else {}

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "lookback_days": int(settings.coaching.weekly_kpi_lookback_days),
        "run_stats": {
            "runs_total": int(run_count),
            "runs_failed": int(failed_runs),
            "runs_live_allowed": int(success_with_trade_modes),
            "runs_risk_blocked": int(risk_blocked_runs),
            "setup_errors": int(setup_errors),
            "error_rate_pct": round(float(error_rate_pct), 2),
        },
        "event_risk_update": {
            "ok_count": int(event_updates_ok),
            "error_count": int(event_updates_error),
        },
        "strategy_snapshot": {
            "swing_profit_factor": float(swing.get("ProfitFactor", 0.0) or 0.0),
            "swing_expectancy": float(swing.get("Expectancy", 0.0) or 0.0),
            "swing_max_dd_pct": float(swing.get("MaxDD", 0.0) or 0.0),
            "swing_trades": int(swing.get("Trades", 0) or 0),
        },
        "live_reconciliation": {
            "status": str((recon or {}).get("status", "")) if isinstance(recon, dict) else "",
            "entry_match_rate_pct": float(recon_coverage.get("entry_match_rate_pct", 0.0) or 0.0),
            "signal_execution_rate_pct": float(recon_coverage.get("signal_execution_rate_pct", 0.0) or 0.0),
            "live_win_rate_pct": float(recon_realized.get("win_rate_pct", 0.0) or 0.0),
            "live_expectancy_r": float(recon_realized.get("expectancy_r", 0.0) or 0.0),
            "live_profit_factor_r": float(recon_realized.get("profit_factor_r", 0.0) or 0.0),
            "live_samples": int(recon_realized.get("samples", 0) or 0),
        },
    }


def _weekly_markdown(payload: dict[str, Any]) -> str:
    rs = payload.get("run_stats", {})
    ev = payload.get("event_risk_update", {})
    ss = payload.get("strategy_snapshot", {})
    lr = payload.get("live_reconciliation", {})
    return (
        f"# Weekly KPI Dashboard\n\n"
        f"- generated_at: {payload.get('generated_at', '')}\n"
        f"- lookback_days: {payload.get('lookback_days', 7)}\n\n"
        f"## Run Stability\n"
        f"- runs_total: {rs.get('runs_total', 0)}\n"
        f"- runs_failed: {rs.get('runs_failed', 0)}\n"
        f"- error_rate_pct: {rs.get('error_rate_pct', 0)}\n"
        f"- runs_live_allowed: {rs.get('runs_live_allowed', 0)}\n"
        f"- runs_risk_blocked: {rs.get('runs_risk_blocked', 0)}\n\n"
        f"## Event Risk Feed\n"
        f"- update_ok: {ev.get('ok_count', 0)}\n"
        f"- update_error: {ev.get('error_count', 0)}\n\n"
        f"## Strategy Snapshot (Swing)\n"
        f"- ProfitFactor: {ss.get('swing_profit_factor', 0)}\n"
        f"- Expectancy: {ss.get('swing_expectancy', 0)}\n"
        f"- MaxDD(%): {ss.get('swing_max_dd_pct', 0)}\n"
        f"- Trades: {ss.get('swing_trades', 0)}\n\n"
        f"## Live Reconciliation\n"
        f"- status: {lr.get('status', '')}\n"
        f"- entry_match_rate_pct: {lr.get('entry_match_rate_pct', 0)}\n"
        f"- signal_execution_rate_pct: {lr.get('signal_execution_rate_pct', 0)}\n"
        f"- live_win_rate_pct: {lr.get('live_win_rate_pct', 0)}\n"
        f"- live_expectancy_r: {lr.get('live_expectancy_r', 0)}\n"
        f"- live_profit_factor_r: {lr.get('live_profit_factor_r', 0)}\n"
        f"- live_samples: {lr.get('live_samples', 0)}\n"
    )


def generate_weekly_kpi_dashboard(settings: Settings) -> dict[str, Any]:
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    events = _collect_recent_events(reports_dir, settings.coaching.weekly_kpi_lookback_days)
    payload = _weekly_kpi_payload(settings, events)

    out_json = Path(settings.coaching.weekly_kpi_path)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_json, payload)

    out_md = reports_dir / "weekly_kpi.md"
    atomic_write_text(out_md, _weekly_markdown(payload), encoding="utf-8")

    return {
        "status": "ok",
        "message": "Weekly KPI dashboard generated",
        "json_path": str(out_json),
        "markdown_path": str(out_md),
        "payload": payload,
    }
