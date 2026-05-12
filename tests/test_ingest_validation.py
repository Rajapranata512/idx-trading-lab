from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import pytest

from src.config import Settings
from src.ingest.load_prices import load_prices_csv, load_prices_from_provider
from src.ingest.validator import validate_prices


def test_load_prices_csv_returns_canonical_columns(tmp_path):
    p = tmp_path / "prices.csv"
    today = datetime.utcnow().strftime("%Y-%m-%d")
    p.write_text(
        "date,ticker,open,high,low,close,volume\n"
        f"{today},bbca,10000,10100,9900,10050,1200000\n",
        encoding="utf-8",
    )
    df = load_prices_csv(str(p))
    assert list(df.columns) == [
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
    assert df.loc[0, "ticker"] == "BBCA"


def test_validate_prices_missing_column_raises():
    bad = pd.DataFrame([{"date": "2026-01-01", "ticker": "BBCA", "close": 10000}])
    with pytest.raises(ValueError, match="Missing required price columns"):
        validate_prices(bad, source="test")


def test_validate_prices_duplicate_rows_raises():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    df = pd.DataFrame(
        [
            {"date": today, "ticker": "BBCA", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1000},
            {"date": today, "ticker": "BBCA", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1000},
        ]
    )
    with pytest.raises(ValueError, match="Duplicate"):
        validate_prices(df, source="test")


def test_validate_prices_ohlc_anomaly_raises():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    df = pd.DataFrame(
        [
            {"date": today, "ticker": "BBCA", "open": 100, "high": 90, "low": 80, "close": 85, "volume": 1000},
        ]
    )
    with pytest.raises(ValueError, match="OHLC consistency"):
        validate_prices(df, source="test")


def test_rest_provider_fallback_to_csv(tmp_path):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    fallback = tmp_path / "fallback.csv"
    fallback.write_text(
        "date,ticker,open,high,low,close,volume\n"
        f"{today},BBCA,10000,10100,9900,10050,1200000\n",
        encoding="utf-8",
    )

    settings_payload = {
        "data": {
            "timezone": "Asia/Jakarta",
            "canonical_prices_path": str(tmp_path / "prices.csv"),
            "fallback_csv_path": str(fallback),
            "universe_csv_path": str(tmp_path / "universe.csv"),
                "provider": {
                    "kind": "rest",
                    "yfinance_fallback_enabled": False,
                    "rest": {
                        "base_url": "http://127.0.0.1:1/not_reachable",
                    "timeout_seconds": 1,
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
        "pipeline": {"min_avg_volume_20d": 200000, "top_n_per_mode": 10, "top_n_combined": 20},
        "risk": {
            "account_size_idr": 10000000,
            "risk_per_trade_pct": 0.75,
            "max_positions": 3,
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
            "min_trades_for_promotion": 150,
            "profit_factor_min": 1.2,
            "expectancy_min": 0.0,
            "max_drawdown_pct_limit": 15.0,
        },
        "notifications": {"telegram_bot_token_env": "TELEGRAM_BOT_TOKEN", "telegram_chat_id_env": "TELEGRAM_CHAT_ID"},
    }
    (tmp_path / "settings.json").write_text(json.dumps(settings_payload), encoding="utf-8")
    (tmp_path / "universe.csv").write_text("ticker\nBBCA\n", encoding="utf-8")

    settings = Settings.model_validate(settings_payload)
    df, source = load_prices_from_provider(settings, tickers=["BBCA"])
    assert source == "csv_fallback"
    assert not df.empty


def test_load_prices_from_provider_surfaces_provider_chain_when_all_sources_fail(tmp_path):
    stale_date = (datetime.utcnow() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    fallback = tmp_path / "fallback.csv"
    fallback.write_text(
        "date,ticker,open,high,low,close,volume\n"
        f"{stale_date},BBCA,10000,10100,9900,10050,1200000\n",
        encoding="utf-8",
    )

    settings_payload = {
        "data": {
            "timezone": "Asia/Jakarta",
            "canonical_prices_path": str(tmp_path / "prices.csv"),
            "fallback_csv_path": str(fallback),
            "universe_csv_path": str(tmp_path / "universe.csv"),
            "provider": {
                "kind": "rest",
                "yfinance_fallback_enabled": False,
                "rest": {
                    "base_url": "http://127.0.0.1:1/not_reachable",
                    "timeout_seconds": 1,
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
        "pipeline": {"min_avg_volume_20d": 200000, "top_n_per_mode": 10, "top_n_combined": 20},
        "risk": {
            "account_size_idr": 10000000,
            "risk_per_trade_pct": 0.75,
            "max_positions": 3,
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
            "min_trades_for_promotion": 150,
            "profit_factor_min": 1.2,
            "expectancy_min": 0.0,
            "max_drawdown_pct_limit": 15.0,
        },
        "notifications": {"telegram_bot_token_env": "TELEGRAM_BOT_TOKEN", "telegram_chat_id_env": "TELEGRAM_CHAT_ID"},
    }
    (tmp_path / "universe.csv").write_text("ticker\nBBCA\n", encoding="utf-8")

    settings = Settings.model_validate(settings_payload)
    with pytest.raises(ValueError) as exc_info:
        load_prices_from_provider(settings, tickers=["BBCA"])

    message = str(exc_info.value)
    assert "All daily providers failed:" in message
    assert "rest=" in message
    assert "csv_fallback=" in message
    assert "stale by" in message.lower()
