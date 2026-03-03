from __future__ import annotations

from pathlib import Path

from src.config import Settings
from src.universe import maybe_auto_update_universe


def _settings(tmp_path: Path) -> Settings:
    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/reference/universe.csv").write_text("ticker,index\nBBCA,LQ45\n", encoding="utf-8")
    payload = {
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
                    "date_from_param_name": "from",
                    "date_to_param_name": "to",
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
            "universe_auto_update": {
                "enabled": True,
                "interval_days": 7,
                "fail_on_error": False,
                "state_path": "reports/universe_update_state.json",
                "request_timeout_seconds": 5,
                "headers": {},
                "query_params": {},
                "lq45": {"url": "", "format": "csv", "ticker_column": "ticker", "query_params": {}},
                "idx30": {"url": "", "format": "csv", "ticker_column": "ticker", "query_params": {}},
            },
        },
        "pipeline": {"min_avg_volume_20d": 100000, "top_n_per_mode": 10, "top_n_combined": 20},
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
            "equity_allocation_pct": 3.0,
            "min_trades_for_promotion": 150,
            "profit_factor_min": 1.2,
            "expectancy_min": 0.0,
            "max_drawdown_pct_limit": 15.0,
        },
        "notifications": {"telegram_bot_token_env": "TELEGRAM_BOT_TOKEN", "telegram_chat_id_env": "TELEGRAM_CHAT_ID"},
    }
    return Settings.model_validate(payload)


def test_universe_auto_update_skips_when_source_url_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = _settings(tmp_path)
    out = maybe_auto_update_universe(settings=settings, force=True)
    assert out["status"] == "skipped_no_source"
    assert Path("data/reference/universe.csv").exists()

