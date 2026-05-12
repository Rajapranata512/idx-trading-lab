from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.config import load_settings
from src.paper_trading import maybe_generate_paper_fills
from src.report.live_reconciliation import write_signal_snapshot


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
        "reconciliation": {
            "enabled": True,
            "auto_reconcile_on_run_daily": True,
            "lookback_days": 90,
            "max_signal_lag_days": 5,
            "fills_csv_path": "data/live/trade_fills.csv",
            "signal_snapshot_dir": "reports/snapshots",
            "output_json_path": "reports/live_reconciliation.json",
            "output_markdown_path": "reports/live_reconciliation.md",
            "details_csv_path": "reports/live_reconciliation_details.csv",
            "unmatched_entries_csv_path": "reports/live_reconciliation_unmatched_entries.csv",
            "fail_on_error": False,
        },
        "paper_trading": {
            "enabled": True,
            "mode": "paper",
            "auto_fill_enabled": True,
            "slippage_pct": 0.1,
            "buy_fee_pct": 0.2,
            "sell_fee_pct": 0.3,
            "state_path": "reports/paper_trading_state.json",
        },
        "notifications": {
            "telegram_bot_token_env": "TELEGRAM_BOT_TOKEN",
            "telegram_chat_id_env": "TELEGRAM_CHAT_ID",
        },
    }
    settings_path = tmp_path / "config/settings.json"
    settings_path.write_text(json.dumps(payload), encoding="utf-8")
    return settings_path


def test_maybe_generate_paper_fills_creates_closed_trade_without_duplicates(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/reference/universe.csv").write_text("ticker,segment\nBBCA,LQ45\n", encoding="utf-8")

    start = pd.Timestamp(datetime.utcnow().date()) - pd.Timedelta(days=14)
    price_rows = []
    for offset in range(12):
        current = start + pd.Timedelta(days=offset)
        open_price = 100 + offset
        high_price = 103 + offset
        low_price = 99 + offset
        close_price = 101 + offset
        if offset == 2:
            high_price = 108
        price_rows.append(
            {
                "date": current.strftime("%Y-%m-%d"),
                "ticker": "BBCA",
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": 1000000,
            }
        )
    prices = pd.DataFrame(price_rows)
    prices_path = tmp_path / settings.data.canonical_prices_path
    prices_path.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(prices_path, index=False)

    signal_time = (start - pd.Timedelta(days=1)).replace(hour=16)
    signal_df = pd.DataFrame(
        [
            {
                "ticker": "BBCA",
                "mode": "swing",
                "score": 81.5,
                "entry": 100.0,
                "stop": 98.0,
                "tp1": 103.0,
                "tp2": 106.0,
                "size": 100,
                "est_roundtrip_cost_pct": 0.7,
            }
        ]
    )
    write_signal_snapshot(
        run_id="20260317_160000",
        signals=signal_df,
        out_dir=settings.reconciliation.signal_snapshot_dir,
        generated_at=signal_time.isoformat(),
    )

    first = maybe_generate_paper_fills(settings=settings)
    assert first["status"] == "ok"
    assert first["generated_count"] == 1
    fills = pd.read_csv(tmp_path / settings.reconciliation.fills_csv_path)
    assert len(fills) == 1
    assert fills.loc[0, "trade_id"].startswith("PAPER:")
    assert fills.loc[0, "ticker"] == "BBCA"
    assert fills.loc[0, "mode"] == "swing"
    assert fills.loc[0, "exit_reason"] in {"tp2_hit", "time_exit", "stop_loss"}

    second = maybe_generate_paper_fills(settings=settings)
    assert second["status"] == "no_new_fills"
    assert second["skipped_existing"] >= 1
    fills_again = pd.read_csv(tmp_path / settings.reconciliation.fills_csv_path)
    assert len(fills_again) == 1


def test_maybe_generate_paper_fills_reports_empty_snapshots_separately(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/reference/universe.csv").write_text("ticker,segment\nBBCA,LQ45\n", encoding="utf-8")

    prices = pd.DataFrame(
        [
            {
                "date": (pd.Timestamp(datetime.utcnow().date()) - pd.Timedelta(days=idx)).strftime("%Y-%m-%d"),
                "ticker": "BBCA",
                "open": 100 + idx,
                "high": 101 + idx,
                "low": 99 + idx,
                "close": 100 + idx,
                "volume": 1000000,
            }
            for idx in range(20)
        ]
    )
    prices_path = tmp_path / settings.data.canonical_prices_path
    prices_path.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(prices_path, index=False)

    write_signal_snapshot(
        run_id="20260317_000000",
        signals=pd.DataFrame(columns=["ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size"]),
        out_dir=settings.reconciliation.signal_snapshot_dir,
        generated_at=datetime.utcnow().isoformat(),
    )

    out = maybe_generate_paper_fills(settings=settings)
    assert out["status"] == "no_signals"
    assert out["snapshot_files_in_window"] == 1
    assert out["signals_total"] == 0
    assert out["valid_signals"] == 0
