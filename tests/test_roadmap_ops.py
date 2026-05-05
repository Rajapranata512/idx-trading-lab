from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from src.cli import _evaluate_data_quality
from src.config import load_settings


def _write_settings(tmp_path: Path, prices_path: str) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/reference/universe.csv").write_text("ticker\nBBCA\nTLKM\n", encoding="utf-8")
    payload = {
        "data": {
            "timezone": "Asia/Jakarta",
            "canonical_prices_path": prices_path,
            "fallback_csv_path": prices_path,
            "universe_csv_path": "data/reference/universe.csv",
            "provider": {
                "kind": "csv",
                "rest": {
                    "base_url": "",
                    "base_url_template": "",
                    "timeout_seconds": 20,
                    "headers": {},
                    "query_params": {},
                    "ticker_param_name": "ticker",
                    "ticker_suffix": "",
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
        "pipeline": {"min_avg_volume_20d": 100000, "top_n_per_mode": 5, "top_n_combined": 10},
        "risk": {
            "account_size_idr": 10000000,
            "risk_per_trade_pct": 0.5,
            "max_positions": 3,
            "daily_loss_stop_r": 1.5,
            "position_lot": 100,
            "stop_atr_multiple": 2.0,
            "tp1_r_multiple": 1.0,
            "tp2_r_multiple": 2.0,
        },
        "backtest": {"buy_fee_pct": 0.2, "sell_fee_pct": 0.3, "slippage_pct": 0.15},
        "notifications": {"telegram_bot_token_env": "TELEGRAM_BOT_TOKEN", "telegram_chat_id_env": "TELEGRAM_CHAT_ID"},
    }
    path = tmp_path / "config/settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_evaluate_data_quality_passes_clean_dataset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    today = datetime.utcnow().date()
    rows = ["date,ticker,open,high,low,close,volume"]
    for idx in range(25):
        d = today - timedelta(days=(24 - idx))
        rows.append(f"{d:%Y-%m-%d},BBCA,{10000+idx},{10020+idx},{9980+idx},{10010+idx},{1000000+idx}")
        rows.append(f"{d:%Y-%m-%d},TLKM,{3500+idx},{3520+idx},{3480+idx},{3510+idx},{2000000+idx}")
    prices_path = "data/raw/prices_daily.csv"
    (tmp_path / prices_path).write_text("\n".join(rows), encoding="utf-8")
    settings = load_settings(_write_settings(tmp_path, prices_path))

    report = _evaluate_data_quality(settings=settings, ingest_info={"missing_tickers_count": 0})
    assert report["status"] == "pass"
    assert report["pass"] is True
    assert report["reason_codes"] == []
    assert Path("reports/data_quality_report.json").exists()


def test_evaluate_data_quality_blocks_problematic_dataset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/raw").mkdir(parents=True, exist_ok=True)
    stale_day = datetime.utcnow().date() - timedelta(days=10)
    rows = [
        "date,ticker,open,high,low,close,volume",
        f"{stale_day:%Y-%m-%d},BBCA,10000,10100,9950,10050,1000000",
        f"{stale_day:%Y-%m-%d},BBCA,10020,10120,9960,10040,1005000",
    ]
    prices_path = "data/raw/prices_daily.csv"
    (tmp_path / prices_path).write_text("\n".join(rows), encoding="utf-8")
    settings = load_settings(_write_settings(tmp_path, prices_path))

    report = _evaluate_data_quality(settings=settings, ingest_info={"missing_tickers_count": 2})
    assert report["status"] == "blocked"
    assert report["pass"] is False
    assert "stale_data" in report["reason_codes"]
    assert "duplicate_rows" in report["reason_codes"]
    assert "missing_tickers" in report["reason_codes"]
