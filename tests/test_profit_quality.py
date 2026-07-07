from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import Settings
from src.risk.profit_quality import apply_profit_quality_gate, build_ticker_edge_profile


def _settings(tmp_path: Path, **profit_quality: object) -> Settings:
    details_path = tmp_path / "reports/live_reconciliation_details.csv"
    profile_path = tmp_path / "reports/ticker_edge_profile.csv"
    report_path = tmp_path / "reports/profit_quality_gate.json"
    payload = {
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
            "min_live_score_t1": 80,
            "min_live_score_swing": 60,
            "profit_quality": {
                "enabled": True,
                "profile_path": str(profile_path),
                "report_path": str(report_path),
                "min_expected_r": 0.05,
                "min_ticker_samples": 3,
                "strong_sample_size": 5,
                "min_ticker_expectancy_r": -0.05,
                "min_ticker_profit_factor_r": 0.85,
                "block_negative_edge": True,
                "gate_without_live_edge": False,
                "gate_with_model_probability": True,
                **profit_quality,
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
            "volatility_targeting_enabled": False,
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
        "reconciliation": {
            "details_csv_path": str(details_path),
            "signal_snapshot_dir": str(tmp_path / "reports/snapshots"),
            "output_json_path": str(tmp_path / "reports/live_reconciliation.json"),
            "output_markdown_path": str(tmp_path / "reports/live_reconciliation.md"),
            "unmatched_entries_csv_path": str(tmp_path / "reports/unmatched.csv"),
        },
        "notifications": {
            "telegram_bot_token_env": "TELEGRAM_BOT_TOKEN",
            "telegram_chat_id_env": "TELEGRAM_CHAT_ID",
        },
    }
    return Settings.model_validate(payload)


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": "AAA", "mode": "swing", "score": 90.0, "entry": 100.0, "stop": 95.0, "tp2": 110.0, "est_roundtrip_cost_pct": 0.2},
            {"ticker": "BBB", "mode": "swing", "score": 80.0, "entry": 100.0, "stop": 95.0, "tp2": 110.0, "est_roundtrip_cost_pct": 0.2},
        ]
    )


def test_ticker_edge_profile_blocks_negative_live_edge(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    details = Path(settings.reconciliation.details_csv_path)
    details.parent.mkdir(parents=True, exist_ok=True)
    details.write_text(
        "executed_at,ticker,signal_mode,realized_r\n"
        "2026-01-01,AAA,swing,-0.40\n"
        "2026-01-02,AAA,swing,-0.30\n"
        "2026-01-03,AAA,swing,-0.20\n"
        "2026-01-01,BBB,swing,0.50\n"
        "2026-01-02,BBB,swing,0.40\n"
        "2026-01-03,BBB,swing,-0.10\n",
        encoding="utf-8",
    )

    profile = build_ticker_edge_profile(details, settings.pipeline.profit_quality.profile_path)
    assert set(profile["ticker"].tolist()) == {"AAA", "BBB"}

    filtered, info = apply_profit_quality_gate(_candidates(), settings=settings, stage="test")

    assert "AAA" not in set(filtered["ticker"].tolist())
    assert "BBB" in set(filtered["ticker"].tolist())
    assert info["blocked_count"] == 1
    assert Path(settings.pipeline.profit_quality.report_path).exists()


def test_model_probability_blocks_low_expected_value_without_live_edge(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    candidates = pd.DataFrame(
        [
            {
                "ticker": "LOWEV",
                "mode": "swing",
                "score": 90.0,
                "shadow_p_win": 0.30,
                "entry": 100.0,
                "stop": 95.0,
                "tp2": 110.0,
                "est_roundtrip_cost_pct": 0.2,
            }
        ]
    )

    filtered, info = apply_profit_quality_gate(candidates, settings=settings, stage="test")

    assert filtered.empty
    assert info["blocked_count"] == 1
    assert info["blocked_preview"][0]["profit_quality_reason"] == "profit_quality_block_low_expected_r"


def test_missing_live_edge_without_model_probability_only_marks_watch(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    candidates = pd.DataFrame(
        [
            {"ticker": "NEW", "mode": "swing", "score": 50.0, "entry": 100.0, "stop": 95.0, "tp2": 110.0, "est_roundtrip_cost_pct": 0.2}
        ]
    )

    filtered, info = apply_profit_quality_gate(candidates, settings=settings, stage="test")

    assert len(filtered) == 1
    assert filtered.iloc[0]["profit_quality_action"] == "watch"
    assert info["blocked_count"] == 0
