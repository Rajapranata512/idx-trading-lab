from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.cli import _maybe_trigger_closed_loop_retrain, compute_features_step, ingest_daily, run_daily, score_step
from src.config import load_settings


def _write_runtime_files(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)

    universe = "ticker\nBBCA\nTLKM\n"
    (tmp_path / "data/reference/universe.csv").write_text(universe, encoding="utf-8")

    today = datetime.utcnow().date()
    dates = pd.date_range(end=today, periods=60, freq="D")
    rows = ["date,ticker,open,high,low,close,volume"]
    for i, d in enumerate(dates):
        rows.append(f"{d:%Y-%m-%d},BBCA,{10000+i},{10030+i},{9980+i},{10010+i},{1200000+i*1000}")
        rows.append(f"{d:%Y-%m-%d},TLKM,{3500+i},{3530+i},{3480+i},{3510+i},{5000000+i*1000}")
    (tmp_path / "data/raw/prices_daily.csv").write_text("\n".join(rows), encoding="utf-8")

    settings = {
        "data": {
            "timezone": "Asia/Jakarta",
            "canonical_prices_path": "data/raw/prices_daily.csv",
            "fallback_csv_path": "data/raw/prices_daily.csv",
            "universe_csv_path": "data/reference/universe.csv",
            "provider": {
                "kind": "csv",
                "rest": {
                    "base_url": "https://example.com",
                    "timeout_seconds": 20,
                    "headers": {},
                    "query_params": {},
                    "ticker_param_name": "ticker",
                    "date_from_param_name": "start",
                    "date_to_param_name": "end",
                    "response_data_path": "",
                    "column_mapping": {
                        "date": "date",
                        "ticker": "ticker",
                        "open": "open",
                        "high": "high",
                        "low": "low",
                        "close": "close",
                        "volume": "volume",
                    },
                },
            },
        },
        "pipeline": {
            "min_avg_volume_20d": 100000,
            "top_n_per_mode": 5,
            "top_n_combined": 10,
            "min_live_score_t1": 0,
            "min_live_score_swing": 0,
            "event_risk": {
                "enabled": True,
                "blacklist_csv_path": "data/reference/event_risk_blacklist.csv",
                "active_statuses": ["SUSPEND", "UMA", "MATERIAL"],
                "default_active_days": 14,
                "fail_on_error": False,
            },
        },
        "risk": {
            "account_size_idr": 10000000,
            "risk_per_trade_pct": 0.75,
            "max_positions": 3,
            "daily_loss_stop_r": 2.0,
            "position_lot": 100,
            "stop_atr_multiple": 2.0,
            "tp1_r_multiple": 1.0,
            "tp2_r_multiple": 2.0,
            "volatility_targeting_enabled": True,
            "volatility_reference_atr_pct": 3.5,
            "volatility_floor_multiplier": 0.5,
            "volatility_cap_multiplier": 1.0,
        },
        "backtest": {
            "buy_fee_pct": 0.15,
            "sell_fee_pct": 0.25,
            "slippage_pct": 0.1,
            "min_trades_for_promotion": 10,
            "profit_factor_min": 1.2,
            "expectancy_min": 0.0,
            "max_drawdown_pct_limit": 15.0,
        },
        "notifications": {"telegram_bot_token_env": "TELEGRAM_BOT_TOKEN", "telegram_chat_id_env": "TELEGRAM_CHAT_ID"},
    }
    settings_path = tmp_path / "config/settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    return settings_path


def test_pipeline_steps_generate_outputs(tmp_path, monkeypatch):
    settings_path = _write_runtime_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    ingest_info = ingest_daily(settings)
    assert ingest_info["rows"] > 0

    feat_info = compute_features_step(settings)
    assert Path(feat_info["out_path"]).exists()

    score_info = score_step(settings)
    assert Path(score_info["signal_path"]).exists()
    payload = json.loads(Path(score_info["signal_path"]).read_text(encoding="utf-8"))
    assert "signals" in payload
    if payload["signals"]:
        row = payload["signals"][0]
        assert "confidence" in row
        assert "model_version" in row
        assert "reason_codes" in row
        assert "gate_flags" in row


def test_run_daily_end_to_end(tmp_path, monkeypatch):
    settings_path = _write_runtime_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    out = run_daily(settings, skip_telegram=True)
    assert Path(out["report_path"]).exists()
    assert Path(out["signal_path"]).exists()
    assert Path("reports/backtest_metrics.json").exists()
    assert Path("reports/data_quality_report.json").exists()
    assert Path("reports/n8n_last_summary.json").exists()
    assert Path("reports/live_config_lock.json").exists()
    assert Path("reports/kpi_baseline_90d.json").exists()
    assert "closed_loop_retrain" in out
    assert "data_quality" in out
    assert "risk_budget" in out
    assert Path(out["n8n_summary_path"]).exists()
    assert out["closed_loop_retrain"]["status"] in {
        "skipped_no_reconciliation_summary",
        "skipped_no_trigger",
        "triggered",
        "triggered_no_update",
        "skipped_cooldown",
        "error",
    }


def test_closed_loop_retrain_skips_without_reconciliation_summary(tmp_path, monkeypatch):
    settings_path = _write_runtime_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    out = _maybe_trigger_closed_loop_retrain(
        settings=settings,
        feat_info={"out_path": "data/processed/features.parquet"},
        reconciliation_info={},
    )
    assert out["status"] == "skipped_no_reconciliation_summary"
    assert out["triggered"] is False


def test_closed_loop_retrain_triggers_force_train(tmp_path, monkeypatch):
    settings_path = _write_runtime_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)
    settings.model_v2.closed_loop_min_live_samples = 5
    settings.model_v2.closed_loop_min_new_fills = 5
    settings.model_v2.closed_loop_min_profit_factor_r = 1.1
    settings.model_v2.closed_loop_min_expectancy_r = 0.0
    settings.model_v2.closed_loop_min_hours_between_retrain = 0

    feat_path = tmp_path / "data/processed/features.parquet"
    feat_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "date": ["2026-01-01"],
            "ticker": ["BBCA"],
            "close": [10000.0],
            "volume": [1000000],
        }
    ).to_parquet(feat_path, index=False)

    called: dict[str, object] = {}

    def _fake_score_history_modes(df: pd.DataFrame, min_avg_volume_20d: int) -> pd.DataFrame:
        called["score_rows"] = int(len(df))
        called["score_min_avg_volume_20d"] = int(min_avg_volume_20d)
        return pd.DataFrame({"date": ["2026-01-01"], "ticker": ["BBCA"], "mode": ["swing"], "close": [10000.0]})

    def _fake_auto_train(scored_history: pd.DataFrame, settings, force: bool = False) -> dict[str, object]:
        called["train_rows"] = int(len(scored_history))
        called["force"] = bool(force)
        return {"status": "updated", "updated": True, "modes": {"swing": {"status": "trained"}}}

    monkeypatch.setattr("src.cli.score_history_modes", _fake_score_history_modes)
    monkeypatch.setattr("src.cli.maybe_auto_train_model_v2", _fake_auto_train)

    reconciliation_info = {
        "summary": {
            "counts": {"fill_entries_total": 25},
            "realized_kpi": {"samples": 12, "profit_factor_r": 0.8, "expectancy_r": -0.05},
        }
    }
    out = _maybe_trigger_closed_loop_retrain(
        settings=settings,
        feat_info={"out_path": str(feat_path)},
        reconciliation_info=reconciliation_info,
    )
    assert out["status"] == "triggered"
    assert out["triggered"] is True
    assert out["new_fills_since_last_trigger"] == 25
    assert "performance_degraded" in out["reasons"]
    assert called["force"] is True
    assert Path(settings.model_v2.closed_loop_state_path).exists()


def test_event_risk_blacklist_excludes_active_ticker(tmp_path, monkeypatch):
    settings_path = _write_runtime_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    today = datetime.utcnow().date().strftime("%Y-%m-%d")
    (tmp_path / "data/reference/event_risk_blacklist.csv").write_text(
        "ticker,status,reason,start_date,end_date,updated_at,source\n"
        f"BBCA,SUSPEND,Test suspend,{today},,{today},test\n",
        encoding="utf-8",
    )
    settings = load_settings(settings_path)

    ingest_daily(settings)
    compute_features_step(settings)
    score_step(settings)

    payload = json.loads(Path("reports/daily_signal.json").read_text(encoding="utf-8"))
    tickers = {str(r.get("ticker", "")) for r in payload.get("signals", [])}
    assert "BBCA" not in tickers
    assert Path("reports/event_risk_excluded.csv").exists()


def test_run_daily_blocks_when_data_quality_stale(tmp_path, monkeypatch):
    settings_path = _write_runtime_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    stale_end = datetime.utcnow().date() - timedelta(days=7)
    stale_dates = pd.date_range(end=stale_end, periods=60, freq="D")
    rows = ["date,ticker,open,high,low,close,volume"]
    for i, d in enumerate(stale_dates):
        rows.append(f"{d:%Y-%m-%d},BBCA,{10000+i},{10030+i},{9980+i},{10010+i},{1200000+i*1000}")
        rows.append(f"{d:%Y-%m-%d},TLKM,{3500+i},{3530+i},{3480+i},{3510+i},{5000000+i*1000}")
    Path("data/raw/prices_daily.csv").write_text("\n".join(rows), encoding="utf-8")

    out = run_daily(settings, skip_telegram=True)
    assert out["data_quality"]["pass"] is False
    assert "stale_data" in out["data_quality"]["reason_codes"]

    summary = json.loads(Path("reports/n8n_last_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "DATA_QUALITY_BLOCKED"
    assert summary["trade_ready"] is False
