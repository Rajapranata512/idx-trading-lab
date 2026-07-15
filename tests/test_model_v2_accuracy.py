from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.analytics import generate_model_v2_accuracy_audit
from src.config import Settings


def _settings(tmp_path: Path) -> Settings:
    payload: dict[str, Any] = {
        "data": {
            "timezone": "Asia/Jakarta",
            "canonical_prices_path": "data/raw/prices_daily.csv",
            "fallback_csv_path": "data/raw/prices_daily.csv",
            "universe_csv_path": "data/reference/universe.csv",
            "provider": {
                "kind": "csv",
                "rest": {
                    "base_url": "",
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
            "active_modes": ["t1"],
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
            "liq_bucket_mid_avg_volume_20d": 750000,
            "liq_bucket_high_avg_volume_20d": 2000000,
        },
        "validation": {
            "threshold_grid_t1": [0, 50, 80],
            "threshold_grid_swing": [0, 50, 70],
            "min_oos_trades": 1,
            "min_train_trades": 1,
        },
        "signal_accuracy": {
            "output_json_path": str(tmp_path / "reports/signal_accuracy_audit.json"),
            "by_ticker_path": str(tmp_path / "reports/signal_accuracy_by_ticker.csv"),
            "by_regime_path": str(tmp_path / "reports/signal_accuracy_by_regime.csv"),
            "by_score_bucket_path": str(tmp_path / "reports/signal_accuracy_by_score_bucket.csv"),
            "max_signals_per_day": 2,
            "precision_top_k": [1, 2],
            "calibration_bins": 4,
            "decay_days": [1, 2],
            "min_trades_per_segment": 1,
        },
        "model_v2_accuracy": {
            "output_json_path": str(tmp_path / "reports/model_v2_accuracy_audit.json"),
            "by_ticker_path": str(tmp_path / "reports/model_v2_by_ticker.csv"),
            "by_regime_path": str(tmp_path / "reports/model_v2_by_regime.csv"),
            "threshold_candidates_path": str(tmp_path / "reports/model_v2_threshold_candidates.csv"),
            "max_candidates_per_day": 2,
            "precision_top_k": [1, 2],
            "calibration_bins": 4,
            "min_trades_per_segment": 1,
            "probability_threshold_grid": [0.3, 0.55, 0.7],
        },
        "model_v2": {
            "horizon_days_t1": 1,
            "horizon_days_swing": 3,
            "min_prob_threshold_t1": 0.55,
            "min_prob_threshold_swing": 0.55,
        },
        "notifications": {
            "telegram_bot_token_env": "TELEGRAM_BOT_TOKEN",
            "telegram_chat_id_env": "TELEGRAM_CHAT_ID",
        },
    }
    return Settings.model_validate(payload)


def _features() -> pd.DataFrame:
    base = pd.Timestamp("2026-01-01")
    rows: list[dict[str, object]] = []
    for offset in range(10):
        date = base + pd.Timedelta(days=offset)
        close_aaa = 100.0 + (offset * 2.0)
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "ticker": "AAA",
                "open": close_aaa - 0.5,
                "high": close_aaa + 9.0,
                "low": close_aaa - 1.0,
                "close": close_aaa,
                "volume": 2000000,
                "avg_vol_20d": 2000000,
                "ma_20": close_aaa - 5.0,
                "ma_50": close_aaa - 10.0,
                "ret_5d": 0.03,
                "ret_20d": 0.08,
                "vol_20d": 0.03,
                "atr_14": 2.0,
                "atr_pct": 2.0,
                "relative_ret_20d": 0.05,
                "dist_high_20": -0.01,
                "turnover_ratio_20d": 1.2,
            }
        )

        close_bbb = 100.0 + (offset * 0.1)
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "ticker": "BBB",
                "open": close_bbb + 0.5,
                "high": close_bbb + 1.0,
                "low": close_bbb - 8.0,
                "close": close_bbb,
                "volume": 1500000,
                "avg_vol_20d": 1500000,
                "ma_20": close_bbb - 3.0,
                "ma_50": close_bbb - 6.0,
                "ret_5d": 0.02,
                "ret_20d": 0.06,
                "vol_20d": 0.04,
                "atr_14": 2.0,
                "atr_pct": 2.2,
                "relative_ret_20d": 0.03,
                "dist_high_20": -0.02,
                "turnover_ratio_20d": 1.0,
            }
        )
    return pd.DataFrame(rows)


def test_model_v2_accuracy_audit_writes_reports_and_improves_selection(tmp_path: Path, monkeypatch: Any) -> None:
    def fake_infer_shadow_scores(candidates: pd.DataFrame, settings: Settings) -> tuple[pd.DataFrame, dict[str, Any]]:
        out = candidates.copy()
        out["shadow_p_win"] = out["ticker"].map({"AAA": 0.8, "BBB": 0.4}).fillna(0.5)
        out["shadow_expected_r"] = out["ticker"].map({"AAA": 0.9, "BBB": -0.4}).fillna(0.0)
        out["shadow_threshold"] = float(settings.model_v2.min_prob_threshold_t1)
        out["shadow_recommended"] = out["shadow_p_win"] >= out["shadow_threshold"]
        out["shadow_model_source"] = "model"
        out["shadow_market_regime"] = "risk_on"
        return out, {
            "status": "ok",
            "message": "fake inference completed",
            "rows": int(len(out)),
            "modes": {"t1": {"rows": int(len(out)), "source": "model", "threshold": 0.55}},
        }

    monkeypatch.setattr("src.analytics.model_v2_accuracy.infer_shadow_scores", fake_infer_shadow_scores)

    settings = _settings(tmp_path)
    payload = generate_model_v2_accuracy_audit(features=_features(), settings=settings)

    assert payload["status"] == "ok"
    assert payload["input"]["audited_trade_count"] > 0
    assert payload["input"]["v2_recommended_count"] > 0
    assert payload["model_source"]["has_fallback"] is False
    assert payload["v2_recommended"]["expectancy_r"] > payload["overall_candidates"]["expectancy_r"]
    assert payload["selection_comparison"]["v2_only"]["trade_count"] >= 0
    assert payload["best_thresholds"]["t1"]["threshold"] in {0.55, 0.7}
    assert payload["precision_at_k"]["combined"][0]["sample_count"] > 0
    assert payload["calibration_v2_recommended"]["status"] == "ok"

    report_paths = payload["report_paths"]
    assert Path(report_paths["json"]).exists()
    assert Path(report_paths["by_ticker_csv"]).exists()
    assert Path(report_paths["by_regime_csv"]).exists()
    assert Path(report_paths["threshold_candidates_csv"]).exists()

    by_ticker = pd.read_csv(report_paths["by_ticker_csv"])
    aaa = by_ticker.loc[by_ticker["ticker"] == "AAA"].iloc[0]
    bbb = by_ticker.loc[by_ticker["ticker"] == "BBB"].iloc[0]
    assert float(aaa["v2_expectancy_r"]) > float(bbb["all_expectancy_r"])

    thresholds = pd.read_csv(report_paths["threshold_candidates_csv"])
    assert set(thresholds["threshold"]) == {0.3, 0.55, 0.7}
