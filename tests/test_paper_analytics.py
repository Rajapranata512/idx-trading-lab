from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.analytics import generate_swing_audit_report
from src.backtest import BacktestCosts
from src.config import load_settings


def _write_settings(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    payload = {
        "data": {
            "timezone": "Asia/Jakarta",
            "canonical_prices_path": "data/raw/prices_daily.csv",
            "fallback_csv_path": "data/raw/prices_daily.sample.csv",
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
            "active_modes": ["swing"],
            "min_live_score_t1": 0,
            "min_live_score_swing": 0,
        },
        "risk": {
            "account_size_idr": 10000000,
            "risk_per_trade_pct": 0.75,
            "max_positions": 3,
            "max_positions_t1": 1,
            "max_positions_swing": 3,
            "daily_loss_stop_r": 2.0,
            "position_lot": 100,
            "stop_atr_multiple": 2.0,
            "tp1_r_multiple": 1.0,
            "tp2_r_multiple": 2.0,
        },
        "backtest": {
            "buy_fee_pct": 0.15,
            "sell_fee_pct": 0.25,
            "slippage_pct": 0.1,
        },
        "notifications": {
            "telegram_bot_token_env": "TELEGRAM_BOT_TOKEN",
            "telegram_chat_id_env": "TELEGRAM_CHAT_ID",
        },
    }
    settings_path = tmp_path / "config/settings.json"
    settings_path.write_text(json.dumps(payload), encoding="utf-8")
    return settings_path


def test_generate_swing_audit_report_groups_trades(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/reference/universe.csv").write_text("ticker,segment\nBBCA,LQ45\nTLKM,IDX30\n", encoding="utf-8")

    base = pd.Timestamp(datetime.utcnow().date()) - pd.Timedelta(days=26)
    rows = []
    for offset in range(16):
        current = base + pd.Timedelta(days=offset)
        rows.append(
            {
                "date": current.strftime("%Y-%m-%d"),
                "ticker": "BBCA",
                "open": 100 + offset,
                "high": 102 + offset,
                "low": 99 + offset,
                "close": 101 + offset,
                "ma_20": 90,
                "ma_50": 88,
                "ret_5d": 0.02,
                "ret_20d": 0.05,
                "vol_20d": 0.03,
                "avg_vol_20d": 1500000,
                "atr_pct": 3.2,
                "atr_14": 2.0,
            }
        )
        rows.append(
            {
                "date": current.strftime("%Y-%m-%d"),
                "ticker": "TLKM",
                "open": 80 + offset,
                "high": 81 + offset,
                "low": 79 + offset,
                "close": 80 + offset,
                "ma_20": 79,
                "ma_50": 78,
                "ret_5d": 0.005,
                "ret_20d": 0.01,
                "vol_20d": 0.015,
                "avg_vol_20d": 1200000,
                "atr_pct": 1.8,
                "atr_14": 1.2,
            }
        )
    features = pd.DataFrame(rows)

    out = generate_swing_audit_report(
        features=features,
        settings=settings,
        costs=BacktestCosts(buy_fee_pct=0.15, sell_fee_pct=0.25, slippage_pct=0.1),
    )
    assert out["status"] == "ok"
    assert out["overall"]["trade_count"] > 0
    assert out["group_source"] == "segment"
    assert out["by_regime"]
    assert out["by_group"]
    assert Path("reports/swing_audit.json").exists()
    assert Path("reports/swing_audit.md").exists()
