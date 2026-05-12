from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.config import load_settings
from src.model_v2.promotion import apply_model_v2_rollout_selection, evaluate_and_update_model_v2_promotion


def _write_settings(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    payload = {
        "data": {
            "timezone": "Asia/Jakarta",
            "canonical_prices_path": "data/raw/prices_daily.csv",
            "fallback_csv_path": "data/raw/prices_daily.sample.csv",
            "universe_csv_path": "data/reference/universe_lq45_idx30.csv",
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
        "backtest": {"buy_fee_pct": 0.15, "sell_fee_pct": 0.25, "slippage_pct": 0.1},
        "reconciliation": {
            "enabled": True,
            "auto_reconcile_on_run_daily": True,
            "lookback_days": 45,
            "max_signal_lag_days": 5,
            "fills_csv_path": "data/live/trade_fills.csv",
            "signal_snapshot_dir": "reports/snapshots",
            "output_json_path": "reports/live_reconciliation.json",
            "output_markdown_path": "reports/live_reconciliation.md",
            "details_csv_path": "reports/live_reconciliation_details.csv",
            "unmatched_entries_csv_path": "reports/live_reconciliation_unmatched_entries.csv",
            "fail_on_error": False,
        },
        "model_v2": {
            "enabled": True,
            "shadow_mode": True,
            "auto_train_enabled": False,
            "promotion": {
                "enabled": True,
                "state_path": "reports/model_v2_promotion_state.json",
                "rollout_levels_pct": [0, 30, 60, 100],
                "consecutive_passes_required": 2,
                "min_live_samples": 30,
                "min_expectancy_r": 0.0,
                "min_profit_factor_r": 1.1,
                "min_entry_match_rate_pct": 40.0,
                "rollback_on_fail": True,
                "rollback_expectancy_r": -0.02,
                "rollback_profit_factor_r": 0.95,
            },
        },
        "notifications": {"telegram_bot_token_env": "TELEGRAM_BOT_TOKEN", "telegram_chat_id_env": "TELEGRAM_CHAT_ID"},
    }
    path = tmp_path / "config/settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_recon(path: Path, status: str, samples: int, expectancy_r: float, profit_factor_r: float, entry_match_rate_pct: float) -> None:
    payload = {
        "status": status,
        "coverage": {"entry_match_rate_pct": entry_match_rate_pct},
        "realized_kpi": {
            "samples": samples,
            "expectancy_r": expectancy_r,
            "profit_factor_r": profit_factor_r,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_promotion_steps_up_after_consecutive_passes(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)
    recon_path = Path(settings.reconciliation.output_json_path)
    recon_path.parent.mkdir(parents=True, exist_ok=True)

    _write_recon(recon_path, status="ok", samples=40, expectancy_r=0.03, profit_factor_r=1.3, entry_match_rate_pct=55.0)
    out1 = evaluate_and_update_model_v2_promotion(settings)
    assert out1["rollout_pct"] == 0
    assert out1["consecutive_passes"] == 1

    out2 = evaluate_and_update_model_v2_promotion(settings)
    assert out2["rollout_pct"] == 30
    assert out2["live_active"] is True


def test_promotion_rolls_back_on_bad_live_metrics(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)
    recon_path = Path(settings.reconciliation.output_json_path)
    recon_path.parent.mkdir(parents=True, exist_ok=True)

    _write_recon(recon_path, status="ok", samples=40, expectancy_r=0.03, profit_factor_r=1.3, entry_match_rate_pct=55.0)
    evaluate_and_update_model_v2_promotion(settings)
    evaluate_and_update_model_v2_promotion(settings)

    _write_recon(recon_path, status="ok", samples=40, expectancy_r=-0.08, profit_factor_r=0.7, entry_match_rate_pct=60.0)
    out = evaluate_and_update_model_v2_promotion(settings)
    assert out["rollout_pct"] == 0
    assert out["reason"] == "rollback_triggered"


def test_apply_rollout_selection_picks_v2_slot_and_v1_fill(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    combined = pd.DataFrame(
        [
            {"ticker": "AAA", "mode": "swing", "score": 90.0, "entry": 1000},
            {"ticker": "BBB", "mode": "swing", "score": 88.0, "entry": 900},
            {"ticker": "CCC", "mode": "swing", "score": 87.0, "entry": 800},
            {"ticker": "DDD", "mode": "swing", "score": 70.0, "entry": 700},
        ]
    )
    shadow_path = Path("reports/model_v2_shadow_signals.csv")
    shadow_path.parent.mkdir(parents=True, exist_ok=True)
    shadow = pd.DataFrame(
        [
            {"ticker": "DDD", "mode": "swing", "shadow_p_win": 0.9, "shadow_recommended": True},
            {"ticker": "AAA", "mode": "swing", "shadow_p_win": 0.4, "shadow_recommended": False},
        ]
    )
    shadow.to_csv(shadow_path, index=False)

    promotion_info = {"live_active": True, "rollout_pct": 30}
    merged, selected, info = apply_model_v2_rollout_selection(
        filtered_combined=combined,
        settings=settings,
        promotion_info=promotion_info,
        shadow_csv_path=str(shadow_path),
    )
    assert len(merged) == 4
    assert len(selected) == 3
    assert info["status"] == "live_rollout"
    assert "DDD" in set(selected["ticker"].tolist())
