from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.cli import compute_features_step, ingest_daily, run_daily, score_step
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


def test_run_daily_end_to_end(tmp_path, monkeypatch):
    settings_path = _write_runtime_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    out = run_daily(settings, skip_telegram=True)
    assert Path(out["report_path"]).exists()
    assert Path(out["signal_path"]).exists()
    assert Path("reports/backtest_metrics.json").exists()


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
