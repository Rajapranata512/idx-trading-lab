from __future__ import annotations

import json
from pathlib import Path

from src.cli import _load_price_reconciliation_reference
from src.config import load_settings


def test_production_settings_enable_stage123_fail_closed_gates():
    settings = load_settings("config/settings.json")

    assert settings.data.universe_auto_update.enabled is True
    assert settings.data.universe_auto_update.fail_on_error is True
    assert settings.data.universe_auto_update.fail_on_stale is True
    assert settings.data.universe_auto_update.expected_lq45_members == 45
    assert settings.data.universe_auto_update.expected_idx30_members == 30
    assert settings.data.price_quality.use_adjusted_for_features is True
    assert settings.data.price_quality.verified_price_events_path.endswith("verified_price_events.csv")
    assert settings.data.price_quality.block_on_active_unresolved_action is True
    assert settings.preopen_auction.enabled is False
    assert settings.preopen_auction.shadow_only is True
    assert settings.preopen_auction.data_license_confirmed is False
    assert settings.preopen_auction.retention_allowed is False
    assert settings.preopen_auction.preliminary_time_local == "08:55:00"
    assert settings.preopen_auction.decision_cutoff_time_local == "08:57:40"


def test_preopen_workflow_has_retry_guard_and_failure_alert():
    workflow = Path(".github/workflows/model-v2-shadow-preopen.yml").read_text(
        encoding="utf-8"
    )

    assert "cron: '5 1 * * 1-5'" in workflow
    assert "cron: '25 1 * * 1-5'" in workflow
    assert "scripts/preopen_delivery_guard.py" in workflow
    assert "Alert Telegram when pre-open delivery fails" in workflow


def test_vercel_watchdog_cron_targets_preopen_endpoint():
    payload = json.loads(Path("web/vercel.json").read_text(encoding="utf-8"))

    assert payload["crons"] == [
        {
            "path": "/api/preopen-watchdog",
            "schedule": "15 1 * * 1-5",
        }
    ]

def test_yfinance_primary_fallback_explains_missing_independent_reconciliation():
    settings = load_settings("config/settings.json")

    reference, source, error = _load_price_reconciliation_reference(
        settings=settings,
        primary_source="yfinance_fallback",
        tickers=["BBCA"],
        start_date="2026-08-01",
        end_date="2026-08-10",
    )

    assert reference is None
    assert source == ""
    assert "EODHD_API_TOKEN" in error
    assert "independent reconciliation" in error
