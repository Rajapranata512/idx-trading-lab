from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.config import load_settings
from src.report.live_reconciliation import reconcile_live_signals, write_signal_snapshot


def _recent_iso(days_ago: int = 1) -> str:
    """Return an ISO timestamp *days_ago* days before now (always within lookback)."""
    return (datetime.utcnow() - timedelta(days=days_ago)).isoformat()


def _write_settings(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
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
        "pipeline": {
            "min_avg_volume_20d": 100000,
            "top_n_per_mode": 5,
            "top_n_combined": 10,
            "min_live_score_t1": 0,
            "min_live_score_swing": 0,
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
        },
        "backtest": {
            "buy_fee_pct": 0.15,
            "sell_fee_pct": 0.25,
            "slippage_pct": 0.1,
        },
        "reconciliation": {
            "enabled": True,
            "auto_reconcile_on_run_daily": True,
            "lookback_days": 30,
            "max_signal_lag_days": 3,
            "fills_csv_path": "data/live/trade_fills.csv",
            "signal_snapshot_dir": "reports/snapshots",
            "output_json_path": "reports/live_reconciliation.json",
            "output_markdown_path": "reports/live_reconciliation.md",
            "details_csv_path": "reports/live_reconciliation_details.csv",
            "unmatched_entries_csv_path": "reports/live_reconciliation_unmatched_entries.csv",
            "fail_on_error": False,
        },
        "notifications": {
            "telegram_bot_token_env": "TELEGRAM_BOT_TOKEN",
            "telegram_chat_id_env": "TELEGRAM_CHAT_ID",
        },
    }
    settings_path = tmp_path / "config/settings.json"
    settings_path.write_text(json.dumps(payload), encoding="utf-8")
    return settings_path


def test_reconcile_live_signals_matches_fill_to_snapshot(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    signal_df = pd.DataFrame(
        [
            {
                "ticker": "BBCA",
                "mode": "swing",
                "score": 80.0,
                "entry": 10000,
                "stop": 9800,
                "tp1": 10200,
                "tp2": 10400,
                "size": 100,
                "est_roundtrip_cost_pct": 0.6,
            }
        ]
    )
    write_signal_snapshot(
        run_id="20260305_160000",
        signals=signal_df,
        out_dir=settings.reconciliation.signal_snapshot_dir,
        generated_at=_recent_iso(2),
    )

    fills_path = Path(settings.reconciliation.fills_csv_path)
    fills_path.parent.mkdir(parents=True, exist_ok=True)
    recent_fill_dt = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    fills_path.write_text(
        "executed_at,ticker,mode,side,qty,price,fee_idr,realized_r,pnl_idr,trade_id,run_id\n"
        f"{recent_fill_dt},BBCA,swing,BUY,100,10010,3500,1.2,25000,T-001,20260305_160000\n",
        encoding="utf-8",
    )

    out = reconcile_live_signals(settings)
    assert out["status"] == "ok"
    assert Path(out["json_path"]).exists()
    assert Path(out["markdown_path"]).exists()
    assert Path(out["details_csv_path"]).exists()

    payload = json.loads(Path(out["json_path"]).read_text(encoding="utf-8"))
    assert payload["counts"]["matched_entries"] == 1
    assert payload["coverage"]["entry_match_rate_pct"] == 100.0


def test_reconcile_live_signals_no_fills(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    signal_df = pd.DataFrame([{"ticker": "TLKM", "mode": "swing", "score": 75.0, "entry": 3500, "size": 100}])
    write_signal_snapshot(
        run_id="20260305_160100",
        signals=signal_df,
        out_dir=settings.reconciliation.signal_snapshot_dir,
        generated_at=_recent_iso(2),
    )

    out = reconcile_live_signals(settings)
    assert out["status"] == "no_fills"
    payload = json.loads(Path(out["json_path"]).read_text(encoding="utf-8"))
    assert payload["counts"]["signals_total"] == 1
    assert payload["counts"]["fill_entries_total"] == 0


def test_reconcile_live_signals_snapshot_exists_but_zero_executable(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    signal_df = pd.DataFrame(columns=["ticker", "mode", "score", "entry", "size"])
    write_signal_snapshot(
        run_id="20260305_170000",
        signals=signal_df,
        out_dir=settings.reconciliation.signal_snapshot_dir,
        generated_at=_recent_iso(2),
    )

    out = reconcile_live_signals(settings)
    assert out["status"] == "no_signals"
    payload = json.loads(Path(out["json_path"]).read_text(encoding="utf-8"))
    assert payload["counts"]["snapshot_files_in_window"] == 1
    assert payload["counts"]["signals_total"] == 0


def test_reconcile_live_signals_returns_schema_error_for_invalid_fills(tmp_path, monkeypatch):
    settings_path = _write_settings(tmp_path)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(settings_path)

    fills_path = Path(settings.reconciliation.fills_csv_path)
    fills_path.parent.mkdir(parents=True, exist_ok=True)
    fills_path.write_text(
        "executed_at,ticker,mode,side,qty,price,fee_idr,realized_r,pnl_idr,trade_id\n"
        "2026-03-06 09:05:00,BBCA,swing,BUY,100,10010,3500,1.2,25000,T-001\n",
        encoding="utf-8",
    )
    out = reconcile_live_signals(settings)
    assert out["status"] == "error_schema"
    payload = json.loads(Path(out["json_path"]).read_text(encoding="utf-8"))
    assert "Missing required columns" in payload["message"]
    assert "run_id" in payload["message"]
