from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import Settings
from src.risk.event_risk_updater import maybe_auto_update_event_risk


def _settings(
    suspend_url: str = "",
    uma_url: str = "",
    material_url: str = "",
) -> Settings:
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
        },
        "pipeline": {
            "min_avg_volume_20d": 100000,
            "top_n_per_mode": 10,
            "top_n_combined": 20,
            "event_risk": {
                "enabled": True,
                "blacklist_csv_path": "data/reference/event_risk_blacklist.csv",
                "active_statuses": ["SUSPEND", "UMA", "MATERIAL"],
                "default_active_days": 14,
                "fail_on_error": False,
                "auto_update": {
                    "enabled": True,
                    "interval_hours": 24,
                    "fail_on_error": False,
                    "state_path": "reports/event_risk_update_state.json",
                    "request_timeout_seconds": 5,
                    "headers": {},
                    "query_params": {},
                    "suspend": {
                        "url": suspend_url,
                        "format": "csv",
                        "ticker_column": "ticker",
                        "status_override": "SUSPEND",
                        "reason_column": "reason",
                        "start_date_column": "start_date",
                        "source_name": "suspend_feed",
                        "query_params": {},
                    },
                    "uma": {
                        "url": uma_url,
                        "format": "csv",
                        "ticker_column": "ticker",
                        "status_override": "UMA",
                        "reason_column": "reason",
                        "start_date_column": "start_date",
                        "source_name": "uma_feed",
                        "query_params": {},
                    },
                    "material": {
                        "url": material_url,
                        "format": "csv",
                        "ticker_column": "ticker",
                        "status_override": "MATERIAL",
                        "reason_column": "reason",
                        "start_date_column": "start_date",
                        "source_name": "material_feed",
                        "query_params": {},
                    },
                },
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


def test_event_risk_auto_update_skips_when_source_url_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/reference/event_risk_blacklist.csv").write_text(
        "ticker,status,reason,start_date,end_date,updated_at,source\n",
        encoding="utf-8",
    )
    settings = _settings()

    out = maybe_auto_update_event_risk(settings=settings, force=True)

    assert out["status"] == "skipped_no_source"
    assert Path("data/reference/event_risk_blacklist.csv").exists()


def test_event_risk_auto_update_writes_blacklist_from_sources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

    suspend_csv = tmp_path / "suspend.csv"
    uma_csv = tmp_path / "uma.csv"
    material_csv = tmp_path / "material.csv"
    suspend_csv.write_text("ticker,reason,start_date\nBBCA,Suspend test,2026-02-20\n", encoding="utf-8")
    uma_csv.write_text("ticker,reason,start_date\nTLKM,UMA test,2026-02-21\n", encoding="utf-8")
    material_csv.write_text("ticker,reason,start_date\nBMRI,Material test,2026-02-22\n", encoding="utf-8")

    settings = _settings(
        suspend_url=suspend_csv.resolve().as_uri(),
        uma_url=uma_csv.resolve().as_uri(),
        material_url=material_csv.resolve().as_uri(),
    )

    out = maybe_auto_update_event_risk(settings=settings, force=True)
    assert out["status"] == "updated"
    assert out["updated"] is True
    assert out["counts"]["rows"] == 3

    blacklist = pd.read_csv("data/reference/event_risk_blacklist.csv")
    assert set(blacklist["ticker"].tolist()) == {"BBCA", "TLKM", "BMRI"}
    assert set(blacklist["status"].tolist()) == {"SUSPEND", "UMA", "MATERIAL"}
    assert Path("reports/event_risk_update_state.json").exists()


def test_event_risk_auto_update_parses_html_feed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

    html_feed = tmp_path / "announcement.html"
    html_feed.write_text(
        "<html><body>"
        "<a href='/a'>Temporary Suspension of Trading [BBCA]</a>"
        "<a href='/b'>Unusual Market Activity [TLKM]</a>"
        "<a href='/c'>Public Expose Material Submission - Incidentil [BMRI]</a>"
        "<a href='/d'>Unsuspension of Trading [BBRI]</a>"
        "</body></html>",
        encoding="utf-8",
    )

    settings = _settings(
        suspend_url=html_feed.resolve().as_uri(),
        uma_url=html_feed.resolve().as_uri(),
        material_url=html_feed.resolve().as_uri(),
    )
    settings.pipeline.event_risk.auto_update.suspend.format = "html"
    settings.pipeline.event_risk.auto_update.uma.format = "html"
    settings.pipeline.event_risk.auto_update.material.format = "html"
    settings.pipeline.event_risk.auto_update.suspend.html_keyword_any = ["suspension"]
    settings.pipeline.event_risk.auto_update.suspend.html_keyword_none = ["unsuspension"]
    settings.pipeline.event_risk.auto_update.uma.html_keyword_any = ["unusual market activity"]
    settings.pipeline.event_risk.auto_update.material.html_keyword_any = ["public expose material"]

    out = maybe_auto_update_event_risk(settings=settings, force=True)
    assert out["status"] == "updated"
    blacklist = pd.read_csv("data/reference/event_risk_blacklist.csv")
    assert set(blacklist["ticker"].tolist()) == {"BBCA", "TLKM", "BMRI"}


def test_event_risk_auto_update_parses_nuxt_announcement_payload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/reference").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

    nuxt_html = tmp_path / "announcement_nuxt.html"
    nuxt_html.write_text(
        "<html><body><script>"
        "__NUXT__=(function(a,b){return {fetch:{x:{announcement:["
        "{Code:\"BBCA\",Title:\"Temporary Suspension of Trading\",PublishDate:\"2026-02-28T00:00:00\"},"
        "{Code:\"TLKM\",Title:\"Unusual Market Activity\",PublishDate:\"2026-02-28T00:00:00\"},"
        "{Code:\"BMRI\",Title:\"Public Expose Material Submission - Incidentil\",PublishDate:\"2026-02-28T00:00:00\"}"
        "]}}};})(1,2);"
        "</script></body></html>",
        encoding="utf-8",
    )

    settings = _settings(
        suspend_url=nuxt_html.resolve().as_uri(),
        uma_url=nuxt_html.resolve().as_uri(),
        material_url=nuxt_html.resolve().as_uri(),
    )
    settings.pipeline.event_risk.auto_update.suspend.format = "html"
    settings.pipeline.event_risk.auto_update.uma.format = "html"
    settings.pipeline.event_risk.auto_update.material.format = "html"
    settings.pipeline.event_risk.auto_update.suspend.html_keyword_any = ["suspension"]
    settings.pipeline.event_risk.auto_update.uma.html_keyword_any = ["unusual market activity"]
    settings.pipeline.event_risk.auto_update.material.html_keyword_any = ["public expose material"]

    out = maybe_auto_update_event_risk(settings=settings, force=True)
    assert out["status"] == "updated"
    blacklist = pd.read_csv("data/reference/event_risk_blacklist.csv")
    assert set(blacklist["ticker"].tolist()) == {"BBCA", "TLKM", "BMRI"}
