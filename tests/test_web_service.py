from __future__ import annotations

import json
import time
from pathlib import Path

from src.web.service import (
    RunJobManager,
    build_dashboard_snapshot,
    query_close_analysis,
    query_close_prices,
    query_signals,
    query_ticker_detail,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def test_query_signals_filters_by_mode_score_and_ticker(tmp_path):
    reports = tmp_path / "reports"
    _write_json(
        reports / "daily_signal.json",
        {
            "generated_at": "2026-03-04T00:00:00",
            "signals": [
                {"ticker": "BBCA", "mode": "t1", "score": 96.5},
                {"ticker": "TLKM", "mode": "swing", "score": 70.2},
                {"ticker": "BMRI", "mode": "t1", "score": 82.0},
            ],
        },
    )

    out = query_signals(reports_dir=reports, mode="t1", min_score=90, ticker_query="BBC", limit=10)
    assert out["total"] == 1
    assert out["count"] == 1
    assert out["items"][0]["ticker"] == "BBCA"
    assert out["by_mode"]["t1"] == 1


def test_build_dashboard_snapshot_reads_reports_contract(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    _write_json(
        reports / "daily_signal.json",
        {
            "generated_at": "2026-03-04T00:00:00",
            "signals": [
                {"ticker": "BBCA", "mode": "t1", "score": 96.5, "entry": 10000, "stop": 9800, "size": 100},
                {"ticker": "TLKM", "mode": "swing", "score": 71.2, "entry": 3500, "stop": 3400, "size": 200},
            ],
        },
    )
    (reports / "execution_plan.csv").write_text(
        "ticker,mode,score,entry,stop,tp1,tp2,size,reason\n"
        "BBCA,t1,96.5,10000,9800,10200,10400,100,quality\n",
        encoding="utf-8",
    )
    (reports / "top_t1.csv").write_text("ticker,mode,score\nBBCA,t1,96.5\n", encoding="utf-8")
    (reports / "top_swing.csv").write_text("ticker,mode,score\nTLKM,swing,71.2\n", encoding="utf-8")
    (reports / "event_risk_active.csv").write_text("ticker,status\nABCD,SUSPEND\n", encoding="utf-8")
    (reports / "event_risk_excluded.csv").write_text("ticker,mode,score\nABCD,t1,94.2\n", encoding="utf-8")
    _write_json(
        reports / "backtest_metrics.json",
        {
            "gate_pass": {"t1": True, "swing": False},
            "regime": {"status": "ok"},
            "kill_switch": {"status": "inactive"},
            "model_v2_promotion": {
                "required_for_live": False,
                "gate_pass": {"t1": True, "swing": True},
            },
            "metrics": {"t1": {"profit_factor": 1.4}},
        },
    )
    _write_json(
        reports / "run_log_20260304.json",
        [
            {"ts": "2026-03-04T00:00:00", "run_id": "20260304_000000", "level": "INFO", "message": "start_run"},
            {
                "ts": "2026-03-04T00:01:00",
                "run_id": "20260304_000000",
                "level": "INFO",
                "message": "ingest_done",
                "extra": {"source": "csv"},
            },
            {
                "ts": "2026-03-04T00:02:00",
                "run_id": "20260304_000000",
                "level": "INFO",
                "message": "live_gate_modes_allowed",
                "extra": {"signal_count": 1},
            },
        ],
    )
    _write_json(
        reports / "model_v2_closed_loop_state.json",
        {
            "last_status": "triggered",
            "last_message": "Closed-loop retrain triggered and updated model artifacts",
            "last_trigger_reasons": ["performance_degraded", "new_fills_ready"],
            "last_evaluated_at": "2026-03-04T00:03:00",
            "last_triggered_at": "2026-03-04T00:03:00",
            "last_seen_fill_entries_total": 40,
            "last_trigger_fill_entries_total": 30,
            "last_live_samples": 26,
            "last_live_profit_factor_r": 0.92,
            "last_live_expectancy_r": -0.01,
            "last_trigger_train_status": "updated",
        },
    )
    _write_json(
        reports / "data_quality_report.json",
        {
            "status": "pass",
            "pass": True,
            "reason_codes": [],
            "checks": {
                "stale_ok": True,
                "missing_ok": True,
                "duplicate_ok": True,
                "missing_tickers_ok": True,
                "outlier_ok": True,
            },
            "stats": {
                "rows_total": 1000,
                "ticker_total": 30,
                "max_data_date": "2026-03-04",
                "stale_days": 0,
                "missing_rows": 0,
                "duplicate_rows": 0,
                "missing_tickers_count": 0,
                "outlier_rows": 0,
            },
            "message": "Data quality checks passed.",
        },
    )
    _write_json(
        reports / "n8n_last_summary.json",
        {
            "status": "SUCCESS",
            "action": "EXECUTE_MAX_3",
            "trade_ready": True,
            "action_reason": "Signals available.",
            "risk_budget_pct": 25.0,
            "risk_budget_status": "micro_live",
            "effective_risk_per_trade_pct": 0.125,
            "hard_daily_stop_r": 2.0,
            "hard_weekly_stop_r": 6.0,
            "paper_live_mode": "micro_live",
            "rollout_phase": "micro_live_025",
            "decision_version": "v2026.03.roadmap_90d",
        },
    )

    snapshot = build_dashboard_snapshot(reports_dir=reports)
    assert snapshot["kpi"]["signal_total"] == 2
    assert snapshot["kpi"]["execution_total"] == 1
    assert snapshot["kpi"]["event_active_total"] == 1
    assert snapshot["backtest"]["gate_pass"]["t1"] is True
    assert snapshot["backtest"]["gate_pass"]["swing"] is False
    assert snapshot["runs"][0]["source"] == "csv"
    assert snapshot["runs"][0]["status"] == "clean"
    assert snapshot["runs"][0]["warning_count"] == 0
    assert snapshot["runs"][0]["error_count"] == 0
    assert snapshot["decision"]["action"] == "EXECUTE_MAX_3"
    assert snapshot["decision"]["trade_ready"] is True
    assert snapshot["decision"]["signal_total"] == 2
    assert snapshot["backtest"]["model_v2_promotion"]["required_for_live"] is False
    assert snapshot["kpi"]["model_v2_promotion_required"] is False
    assert snapshot["closed_loop_retrain"]["status"] == "triggered"
    assert snapshot["closed_loop_retrain"]["triggered"] is True
    assert "performance_degraded" in snapshot["closed_loop_retrain"]["reasons"]
    assert snapshot["kpi"]["closed_loop_retrain_status"] == "triggered"
    assert snapshot["kpi"]["closed_loop_retrain_triggered"] is True
    assert snapshot["quality"]["status"] == "pass"
    assert snapshot["quality"]["pass"] is True
    assert snapshot["risk_budget"]["risk_budget_pct"] == 25.0
    assert snapshot["paper_live_mode"]["mode"] == "micro_live"
    assert snapshot["kpi"]["quality_pass"] is True
    assert snapshot["kpi"]["risk_budget_status"] == "micro_live"
    assert snapshot["kpi"]["paper_live_mode"] == "micro_live"


def test_build_dashboard_snapshot_groups_recent_runs_per_run_id_and_exposes_issues(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    _write_json(
        reports / "run_log_20260317.json",
        [
            {
                "ts": "2026-03-17T10:00:00",
                "run_id": "20260317_100000",
                "level": "INFO",
                "message": "start_run",
            },
            {
                "ts": "2026-03-17T10:01:00",
                "run_id": "20260317_100000",
                "level": "WARN",
                "message": "live_gate_blocked",
                "extra": {
                    "gate_pass": {"t1": False, "swing": False},
                    "regime": {"status": "risk_off", "reason": "Failed checks: breadth_ma20_ok"},
                    "kill_switch": {"status": "clear"},
                },
            },
            {
                "ts": "2026-03-17T11:00:00",
                "run_id": "20260317_110000",
                "level": "INFO",
                "message": "start_run",
            },
            {
                "ts": "2026-03-17T11:01:00",
                "run_id": "20260317_110000",
                "level": "ERROR",
                "message": "run_failed",
                "extra": {"error": "Data is stale by 23 days (> 10)"},
            },
        ],
    )

    snapshot = build_dashboard_snapshot(reports_dir=reports)
    assert len(snapshot["runs"]) == 2
    assert snapshot["runs"][0]["run_id"] == "20260317_110000"
    assert snapshot["runs"][0]["status"] == "failed"
    assert snapshot["runs"][0]["status_category"] == "critical_failure"
    assert snapshot["runs"][0]["status_tone"] == "critical"
    assert snapshot["runs"][0]["error_count"] == 1
    assert snapshot["runs"][0]["warning_count"] == 0
    assert snapshot["runs"][0]["issues"][0]["detail"] == "Data is stale by 23 days (> 10)"
    assert snapshot["runs"][0]["issues"][0]["category"] == "critical_failure"
    assert snapshot["runs"][0]["issues"][0]["category_label"] == "Critical failure"

    assert snapshot["runs"][1]["run_id"] == "20260317_100000"
    assert snapshot["runs"][1]["status"] == "warning"
    assert snapshot["runs"][1]["status_category"] == "protective_warning"
    assert snapshot["runs"][1]["status_tone"] == "protective"
    assert snapshot["runs"][1]["error_count"] == 0
    assert snapshot["runs"][1]["warning_count"] == 1
    assert "No mode passed the live gate" in snapshot["runs"][1]["issues"][0]["detail"]
    assert snapshot["runs"][1]["issues"][0]["category"] == "protective_warning"
    assert snapshot["runs"][1]["issues"][0]["category_label"] == "Protective warning"


def test_build_dashboard_snapshot_decision_flags_model_v2_promotion_block(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    _write_json(
        reports / "daily_signal.json",
        {
            "generated_at": "2026-03-04T00:00:00",
            "signals": [
                {"ticker": "BBCA", "mode": "t1", "score": 91.5, "entry": 10000, "stop": 9800, "size": 100},
            ],
        },
    )
    _write_json(
        reports / "backtest_metrics.json",
        {
            "gate_pass": {"t1": False, "swing": False},
            "regime": {"status": "ok"},
            "kill_switch": {"status": "clear"},
            "gate_components": {
                "t1": {
                    "model_gate_ok": True,
                    "regime_ok": True,
                    "kill_switch_ok": True,
                    "promotion_required": True,
                    "promotion_gate_ok": False,
                    "final_ok": False,
                },
                "swing": {
                    "model_gate_ok": False,
                    "regime_ok": True,
                    "kill_switch_ok": True,
                    "promotion_required": True,
                    "promotion_gate_ok": False,
                    "final_ok": False,
                },
            },
            "model_v2_promotion": {
                "enabled": True,
                "shadow_mode": False,
                "required_for_live": True,
                "gate_pass": {"t1": False, "swing": False},
                "modes": {
                    "t1": {"passed": False, "reasons": ["Median ProfitFactor (0.80) < minimum (1.25)"]},
                    "swing": {"passed": False, "reasons": ["Total OOS trades (80) < minimum (120)"]},
                },
            },
        },
    )

    snapshot = build_dashboard_snapshot(reports_dir=reports)
    decision = snapshot["decision"]
    assert decision["trade_ready"] is False
    assert decision["status"] == "MODEL_V2_PROMOTION_BLOCKED"
    assert decision["model_v2_promotion_required"] is True
    assert sorted(decision["model_v2_promotion_blocked_modes"]) == ["swing", "t1"]
    assert any("promotion gate blocked" in str(item).lower() for item in decision["why_no_signal"])


def test_build_dashboard_snapshot_closed_loop_defaults_when_state_missing(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    _write_json(
        reports / "daily_signal.json",
        {
            "generated_at": "2026-03-04T00:00:00",
            "signals": [],
        },
    )

    snapshot = build_dashboard_snapshot(reports_dir=reports)
    assert snapshot["closed_loop_retrain"]["status"] == "not_run"
    assert snapshot["closed_loop_retrain"]["triggered"] is False
    assert snapshot["kpi"]["closed_loop_retrain_status"] == "not_run"
    assert snapshot["quality"]["status"] == "not_run"
    assert snapshot["risk_budget"]["status"] == "unknown"
    assert snapshot["paper_live_mode"]["mode"] == "unknown"


def test_run_job_manager_succeeds_and_records_result():
    def fake_runner(settings_path: str, skip_telegram: bool):
        return {"settings_path": settings_path, "skip_telegram": skip_telegram}

    manager = RunJobManager(runner=fake_runner, max_workers=1, max_history=5)
    submitted = manager.submit(settings_path="config/settings.json", skip_telegram=True)
    job_id = submitted["job_id"]

    final = None
    for _ in range(80):
        final = manager.get(job_id)
        if final and final["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)

    assert final is not None
    assert final["status"] == "succeeded"
    assert final["result"]["settings_path"] == "config/settings.json"
    assert final["result"]["skip_telegram"] is True


def test_query_ticker_detail_reads_intraday_and_reason_breakdown(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    data_raw = tmp_path / "data/raw"
    data_raw.mkdir(parents=True, exist_ok=True)

    _write_json(
        reports / "intraday_signal.json",
        {
            "generated_at": "2026-03-04T10:00:00",
            "signals": [
                {
                    "ticker": "BBCA",
                    "mode": "intraday",
                    "score": 81.5,
                    "entry": 10000,
                    "stop": 9850,
                    "tp1": 10180,
                    "tp2": 10350,
                    "size": 100,
                    "reason": "Trend MA50 + momentum 20D + ATR expansion",
                }
            ],
        },
    )
    (data_raw / "prices_intraday.csv").write_text(
        "timestamp,ticker,open,high,low,close,volume,timeframe\n"
        "2026-03-04T09:00:00,BBCA,9950,10010,9940,10000,250000,5m\n"
        "2026-03-04T09:05:00,BBCA,10000,10040,9990,10030,220000,5m\n"
        "2026-03-04T09:10:00,BBCA,10030,10060,10020,10050,215000,5m\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    payload = query_ticker_detail(ticker="BBCA", reports_dir=reports, bars=120)
    assert payload["ticker"] == "BBCA"
    assert payload["series_type"] == "intraday"
    assert payload["bar_count"] >= 3
    assert payload["chart"]["has_data"] is True
    assert payload["levels"]["entry"] == 10000
    assert any("Trend" in r["factor"] for r in payload["reason_breakdown"])


def test_query_close_analysis_returns_close_metrics(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    data_raw = tmp_path / "data/raw"
    data_raw.mkdir(parents=True, exist_ok=True)

    _write_json(
        reports / "daily_signal.json",
        {
            "generated_at": "2026-03-04T00:00:00",
            "signals": [
                {"ticker": "BBCA", "mode": "swing", "score": 82.5},
                {"ticker": "TLKM", "mode": "swing", "score": 71.2},
            ],
        },
    )
    (data_raw / "prices_daily.csv").write_text(
        "date,ticker,open,high,low,close,volume\n"
        "2026-02-25,BBCA,10000,10100,9950,10050,1000000\n"
        "2026-02-26,BBCA,10050,10150,10010,10100,1200000\n"
        "2026-02-27,BBCA,10100,10200,10080,10180,1300000\n"
        "2026-03-02,BBCA,10180,10250,10120,10200,1250000\n"
        "2026-03-03,BBCA,10200,10300,10190,10280,1500000\n"
        "2026-03-04,BBCA,10280,10320,10220,10300,1600000\n"
        "2026-03-03,TLKM,3500,3550,3480,3520,4000000\n"
        "2026-03-04,TLKM,3520,3560,3510,3550,4200000\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    payload = query_close_analysis(reports_dir=reports, min_close=3000, min_avg_volume=100000, limit=50)
    assert payload["count"] >= 2
    assert payload["items"][0]["ticker"] in {"BBCA", "TLKM"}
    assert "last_close" in payload["items"][0]
    assert "chg_1d_pct" in payload["items"][0]
    assert "ma20" in payload["items"][0]


def test_query_close_prices_returns_raw_close_rows(tmp_path, monkeypatch):
    data_raw = tmp_path / "data/raw"
    data_raw.mkdir(parents=True, exist_ok=True)
    (data_raw / "prices_daily.csv").write_text(
        "date,ticker,open,high,low,close,volume\n"
        "2026-03-03,BBCA,10200,10300,10190,10280,1500000\n"
        "2026-03-04,BBCA,10280,10320,10220,10300,1600000\n"
        "2026-03-03,TLKM,3500,3550,3480,3520,4000000\n"
        "2026-03-04,TLKM,3520,3560,3510,3550,4200000\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    payload = query_close_prices(
        reports_dir=tmp_path / "reports",
        ticker_query="BBC",
        start_date="2026-03-03",
        end_date="2026-03-04",
        limit=100,
    )
    assert payload["total"] == 2
    assert payload["count"] == 2
    assert all(str(row["ticker"]) == "BBCA" for row in payload["items"])
    assert "close" in payload["items"][0]

    payload_all = query_close_prices(
        reports_dir=tmp_path / "reports",
        ticker_query="",
        start_date="2026-03-03",
        end_date="2026-03-04",
        limit=0,
    )
    assert payload_all["total"] == 4
    assert payload_all["count"] == 4
