from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.config import load_settings
from src.risk.volatility_recalibration import maybe_auto_recalibrate_volatility_targets


def _write_settings(tmp_path: Path) -> Path:
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
        },
        "risk": {
            "account_size_idr": 10000000,
            "risk_per_trade_pct": 0.5,
            "max_positions": 3,
            "daily_loss_stop_r": 2.0,
            "position_lot": 100,
            "stop_atr_multiple": 2.0,
            "tp1_r_multiple": 1.0,
            "tp2_r_multiple": 2.0,
            "volatility_targeting_enabled": True,
            "volatility_reference_atr_pct": 4.5,
            "volatility_reference_realized_pct": 3.3,
            "volatility_floor_multiplier": 0.5,
            "volatility_cap_multiplier": 1.15,
            "volatility_targeting_mode": "hybrid",
            "volatility_market_weight": 0.55,
            "volatility_auto_recalibration_enabled": True,
            "volatility_auto_recalibration_interval_days": 7,
            "volatility_auto_recalibration_state_path": "reports/volatility_recalibration_state.json",
            "volatility_auto_recalibration_lookback_days": 252,
            "volatility_auto_recalibration_min_rows": 30,
            "volatility_auto_recalibration_quantile_atr": 0.5,
            "volatility_auto_recalibration_quantile_realized": 0.5,
            "volatility_auto_recalibration_min_atr_pct": 1.5,
            "volatility_auto_recalibration_max_atr_pct": 8.0,
            "volatility_auto_recalibration_min_realized_pct": 0.8,
            "volatility_auto_recalibration_max_realized_pct": 6.0,
            "volatility_auto_recalibration_min_delta_pct": 0.05,
            "max_position_exposure_pct": 20.0,
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
        "notifications": {
            "telegram_bot_token_env": "TELEGRAM_BOT_TOKEN",
            "telegram_chat_id_env": "TELEGRAM_CHAT_ID",
        },
    }
    path = tmp_path / "config/settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path


def _write_features(tmp_path: Path) -> Path:
    rows = []
    dates = pd.date_range(end=datetime.utcnow().date(), periods=80, freq="D")
    for i, d in enumerate(dates):
        rows.append(
            {
                "date": d,
                "ticker": "AAA",
                "atr_pct": 2.5 + (i % 5) * 0.1,
                "vol_20d": 0.015 + (i % 4) * 0.001,
            }
        )
        rows.append(
            {
                "date": d,
                "ticker": "BBB",
                "atr_pct": 3.0 + (i % 5) * 0.1,
                "vol_20d": 0.020 + (i % 4) * 0.001,
            }
        )
    frame = pd.DataFrame(rows)
    path = tmp_path / "data/processed/features.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def test_recalibration_updates_targets_and_persists(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    features_path = _write_features(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    out = maybe_auto_recalibrate_volatility_targets(
        settings=settings,
        settings_path=settings_path,
        force=True,
        features_path=features_path,
    )

    assert out["status"] == "updated"
    assert out["updated"] is True
    assert float(settings.risk.volatility_reference_atr_pct) != 4.5
    assert float(settings.risk.volatility_reference_realized_pct) != 3.3

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert float(payload["risk"]["volatility_reference_atr_pct"]) == float(settings.risk.volatility_reference_atr_pct)
    assert float(payload["risk"]["volatility_reference_realized_pct"]) == float(
        settings.risk.volatility_reference_realized_pct
    )


def test_recalibration_respects_interval_skip(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    features_path = _write_features(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    state_path = tmp_path / "reports/volatility_recalibration_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"last_success_at": datetime.utcnow().isoformat()}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    out = maybe_auto_recalibrate_volatility_targets(
        settings=settings,
        settings_path=settings_path,
        force=False,
        features_path=features_path,
    )

    assert out["status"] == "skipped_interval"

