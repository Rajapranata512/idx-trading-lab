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
    assert settings.data.price_quality.reconciliation_evidence_enabled is True
    assert settings.data.price_quality.reconciliation_required is False
    assert settings.data.price_quality.reconciliation_min_coverage_ratio == 0.95
    assert settings.data.price_quality.reconciliation_min_consecutive_sessions == 5
    assert settings.data.price_quality.provider_account_probe_enabled is True
    assert (
        settings.data.price_quality.provider_account_status_url
        == "https://eodhd.com/api/user"
    )
    assert settings.data.price_quality.provider_account_token_env == "EODHD_API_TOKEN"
    deferred = settings.data.price_quality.deferred_eod_reconciliation
    assert deferred.enabled is True
    assert deferred.use_yfinance_as_daily_primary is True
    assert deferred.batch_size == 15
    assert settings.data.price_quality.provider_account_minimum_reserve_calls == 5
    assert settings.preopen_auction.enabled is False
    assert settings.preopen_auction.shadow_only is True
    assert settings.preopen_auction.data_license_confirmed is False
    assert settings.preopen_auction.retention_allowed is False
    assert settings.preopen_auction.preliminary_time_local == "08:55:00"
    assert settings.preopen_auction.decision_cutoff_time_local == "08:57:40"


def test_daily_workflow_preflights_eod_reconciliation_secret():
    workflow = Path(".github/workflows/daily-run.yml").read_text(encoding="utf-8")

    assert "Verify EOD reconciliation configuration" in workflow
    assert "python -m src.cli check-eod-reconciliation-readiness" in workflow
    assert "python -m src.cli check-eod-provider-account" not in workflow
    assert "python -m src.cli collect-deferred-eod-reconciliation" in workflow
    assert "EODHD_API_TOKEN: ${{ secrets.EODHD_API_TOKEN }}" in workflow


def test_daily_workflow_never_publishes_stale_generated_artifacts():
    workflow = Path(".github/workflows/daily-run.yml").read_text(encoding="utf-8")

    assert "git fetch --no-tags origin main" in workflow
    assert 'remote_sha="$(git rev-parse FETCH_HEAD)"' in workflow
    assert 'if [ "$remote_sha" != "$GITHUB_SHA" ]; then' in workflow
    assert "Stale workflow base" in workflow
    assert "git push origin HEAD:main" in workflow
    assert 'if [ "$latest_sha" != "$GITHUB_SHA" ]; then' in workflow
    assert "Concurrent main update" in workflow
    assert "git rebase" not in workflow
    assert "git push --force" not in workflow


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
        primary_provider_failures=[
            "rest=HTTPError: HTTP Error 402: Payment Required"
        ],
    )

    assert reference is None
    assert source == ""
    assert "402" in error
    assert "entitlement/quota" in error
    assert "independent reconciliation" in error
