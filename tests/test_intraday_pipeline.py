from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.config import load_settings
from src.intraday.daemon import run_intraday_daemon
from src.intraday.pipeline import run_intraday_once


def _write_runtime_files(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)

    (tmp_path / "data/reference/universe.csv").write_text("ticker\nBBCA\nTLKM\n", encoding="utf-8")

    now = pd.Timestamp.utcnow().tz_localize(None)
    intraday_dates = pd.date_range(end=now, periods=120, freq="5min")
    rows = ["timestamp,ticker,open,high,low,close,volume,timeframe"]
    for i, ts in enumerate(intraday_dates):
        rows.append(
            f"{ts:%Y-%m-%dT%H:%M:%S},BBCA,{10000+i},{10020+i},{9980+i},{10010+i},{300000+i*100},5m"
        )
        rows.append(
            f"{ts:%Y-%m-%dT%H:%M:%S},TLKM,{3500+i},{3520+i},{3490+i},{3510+i},{500000+i*120},5m"
        )
    (tmp_path / "data/raw/prices_intraday.csv").write_text("\n".join(rows), encoding="utf-8")
    (tmp_path / "data/raw/prices_intraday.sample.csv").write_text("\n".join(rows), encoding="utf-8")

    today = datetime.utcnow().date()
    daily_dates = pd.date_range(end=today, periods=90, freq="D")
    daily_rows = ["date,ticker,open,high,low,close,volume"]
    for i, d in enumerate(daily_dates):
        daily_rows.append(f"{d:%Y-%m-%d},BBCA,{10000+i},{10030+i},{9980+i},{10010+i},{1200000+i*1000}")
        daily_rows.append(f"{d:%Y-%m-%d},TLKM,{3500+i},{3530+i},{3480+i},{3510+i},{5000000+i*1000}")
    (tmp_path / "data/raw/prices_daily.csv").write_text("\n".join(daily_rows), encoding="utf-8")

    settings = {
        "data": {
            "timezone": "Asia/Jakarta",
            "canonical_prices_path": "data/raw/prices_daily.csv",
            "fallback_csv_path": "data/raw/prices_daily.csv",
            "universe_csv_path": "data/reference/universe.csv",
            "intraday": {
                "enabled": True,
                "timeframe": "5m",
                "lookback_minutes": 300,
                "poll_seconds": 10,
                "max_rows_per_ticker": 300,
                "canonical_prices_path": "data/raw/prices_intraday.csv",
                "fallback_csv_path": "data/raw/prices_intraday.sample.csv",
                "websocket_enabled": False,
                "websocket_url": "",
                "websocket_subscribe_payload": "",
                "websocket_timeout_seconds": 10,
                "reconnect_max_attempts": 4,
                "reconnect_backoff_seconds": 1,
                "reconnect_max_backoff_seconds": 5,
                "auto_refresh_web_seconds": 20,
                "min_avg_volume_20bars": 100000,
                "min_live_score": 30.0,
                "top_n": 10,
            },
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
                "enabled": False,
                "blacklist_csv_path": "data/reference/event_risk_blacklist.csv",
                "active_statuses": ["SUSPEND", "UMA", "MATERIAL"],
                "default_active_days": 14,
                "fail_on_error": False,
            },
        },
        "risk": {
            "account_size_idr": 10000000,
            "risk_per_trade_pct": 0.5,
            "max_positions": 3,
            "daily_loss_stop_r": 1.5,
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
            "buy_fee_pct": 0.2,
            "sell_fee_pct": 0.3,
            "slippage_pct": 0.15,
            "min_trades_for_promotion": 10,
            "profit_factor_min": 1.2,
            "expectancy_min": 0.0,
            "max_drawdown_pct_limit": 15.0,
        },
        "notifications": {
            "telegram_bot_token_env": "TELEGRAM_BOT_TOKEN",
            "telegram_chat_id_env": "TELEGRAM_CHAT_ID",
        },
    }
    settings_path = tmp_path / "config/settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    return settings_path


def test_run_intraday_once_generates_outputs(tmp_path, monkeypatch):
    settings_path = _write_runtime_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    out = run_intraday_once(settings)
    assert out["signals"]["signal_count"] >= 1
    assert Path("reports/intraday_signal.json").exists()
    payload = json.loads(Path("reports/intraday_signal.json").read_text(encoding="utf-8"))
    assert len(payload.get("signals", [])) >= 1


def test_run_intraday_daemon_writes_state(tmp_path, monkeypatch):
    settings_path = _write_runtime_files(tmp_path)
    monkeypatch.chdir(tmp_path)

    run_intraday_daemon(settings_path=str(settings_path), max_loops=1)
    state_path = Path("reports/intraday_daemon_state.json")
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state.get("status") in {"ok", "error"}

