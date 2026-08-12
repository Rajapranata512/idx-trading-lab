from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.config import load_settings
from src.ingest.deferred_reconciliation import collect_deferred_eod_reconciliation
from src.ingest.load_prices import load_prices_from_provider
from src.ingest.providers.rest_provider import RestEodProvider
from src.ingest.providers.yfinance_provider import YFinanceProvider


def _account_payload(_url: str, _timeout: int) -> dict[str, object]:
    return {
        "subscriptionType": "free",
        "apiRequests": 0,
        "apiRequestsDate": "2026-08-12",
        "dailyRateLimit": 20,
        "extraLimit": 0,
    }


def _settings(tmp_path: Path):
    settings = load_settings("config/settings.json")
    universe = [f"T{index:02d}" for index in range(45)]
    universe_path = tmp_path / "universe.csv"
    pd.DataFrame({"ticker": universe}).to_csv(universe_path, index=False)
    settings.data.universe_csv_path = str(universe_path)
    settings.data.canonical_prices_path = str(tmp_path / "prices.csv")

    deferred = settings.data.price_quality.deferred_eod_reconciliation
    deferred.cache_path = str(tmp_path / "deferred_cache.csv")
    deferred.state_path = str(tmp_path / "deferred_state.json")
    deferred.report_path = str(tmp_path / "deferred_report.json")
    deferred.details_path = str(tmp_path / "deferred_details.csv")
    deferred.batch_size = 15
    deferred.lookback_calendar_days = 45
    deferred.cache_retention_calendar_days = 180

    dates = pd.bdate_range("2026-08-03", periods=7)
    rows = []
    for ticker_index, ticker in enumerate(universe):
        for date_index, session_date in enumerate(dates):
            close = float(100 + ticker_index + date_index)
            rows.append(
                {
                    "date": session_date.strftime("%Y-%m-%d"),
                    "ticker": ticker,
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1_000_000,
                    "source": "yfinance_primary",
                    "ingested_at": "2026-08-12T10:00:00+00:00",
                }
            )
    pd.DataFrame(rows).to_csv(settings.data.canonical_prices_path, index=False)
    return settings, universe, pd.DataFrame(rows)


def test_deferred_collection_rotates_15_tickers_and_is_same_day_idempotent(
    tmp_path: Path,
):
    settings, universe, prices = _settings(tmp_path)
    calls: list[str] = []

    def fetcher(ticker: str, _start: str, _end: str) -> pd.DataFrame:
        calls.append(ticker)
        return prices[prices["ticker"].eq(ticker)].copy()

    first = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 12, 10, tzinfo=timezone.utc),
        fetcher=fetcher,
        account_fetcher=_account_payload,
        environ={"EODHD_API_TOKEN": "test-secret"},
    )
    second = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 12, 11, tzinfo=timezone.utc),
        fetcher=lambda *_args: pytest.fail("same-day retry must not fetch tickers"),
        account_fetcher=lambda *_args: pytest.fail(
            "same-day retry must not call account endpoint"
        ),
        environ={"EODHD_API_TOKEN": "test-secret"},
    )

    assert first["status"] == "collecting"
    assert first["batch"]["selected_tickers"] == universe[:15]
    assert len(calls) == 15
    assert second["batch"]["idempotent_skip"] is True
    assert second["batch"]["selected_tickers"] == []
    assert second["account"]["required_calls"] == 0
    assert "test-secret" not in json.dumps(first)


def test_three_daily_batches_build_full_universe_five_session_research_audit(
    tmp_path: Path,
):
    settings, universe, prices = _settings(tmp_path)
    calls: list[str] = []

    def fetcher(ticker: str, _start: str, _end: str) -> pd.DataFrame:
        calls.append(ticker)
        return prices[prices["ticker"].eq(ticker)].copy()

    outputs = []
    for day in [12, 13, 14]:
        outputs.append(
            collect_deferred_eod_reconciliation(
                settings,
                now=datetime(2026, 8, day, 10, tzinfo=timezone.utc),
                fetcher=fetcher,
                account_fetcher=_account_payload,
                environ={"EODHD_API_TOKEN": "test-secret"},
            )
        )

    assert len(calls) == 45
    assert calls == universe
    assert outputs[1]["status"] == "collecting"
    final = outputs[2]
    assert final["status"] == "pass"
    assert final["research_evidence_eligible"] is True
    assert final["same_day_reconciliation"] is False
    assert final["final_execution_eligible"] is False
    assert final["sources"] == {
        "daily_primary": "yfinance_primary",
        "deferred_reference": "eodhd_deferred",
    }
    assert final["audit"]["coverage_ratio"] == 1.0
    assert final["audit"]["mismatch_ratio"] == 0.0
    assert len(final["audit"]["session_dates"]) == 5

    cache = pd.read_csv(
        settings.data.price_quality.deferred_eod_reconciliation.cache_path
    )
    details = pd.read_csv(
        settings.data.price_quality.deferred_eod_reconciliation.details_path
    )
    assert cache["ticker"].nunique() == 45
    assert len(details) == 45 * 5


def test_deferred_collection_blocks_without_consuming_ticker_calls_when_quota_is_low(
    tmp_path: Path,
):
    settings, _universe, _prices = _settings(tmp_path)

    result = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 12, 10, tzinfo=timezone.utc),
        fetcher=lambda *_args: pytest.fail(
            "ticker fetch must not run when account quota is insufficient"
        ),
        account_fetcher=lambda _url, _timeout: {
            "subscriptionType": "free",
            "apiRequests": 20,
            "apiRequestsDate": "2026-08-12",
            "dailyRateLimit": 20,
            "extraLimit": 0,
        },
        environ={"EODHD_API_TOKEN": "test-secret"},
    )

    assert result["status"] == "blocked"
    assert result["batch"]["selected_tickers"] == []
    assert result["account"]["remaining_calls"] == 0
    assert result["final_execution_eligible"] is False


def test_deferred_collection_accepts_previous_utc_usage_date_after_reset(
    tmp_path: Path,
):
    settings, universe, prices = _settings(tmp_path)
    calls: list[str] = []

    def fetcher(ticker: str, _start: str, _end: str) -> pd.DataFrame:
        calls.append(ticker)
        return prices[prices["ticker"].eq(ticker)].copy()

    result = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 12, 10, tzinfo=timezone.utc),
        fetcher=fetcher,
        account_fetcher=lambda _url, _timeout: {
            "subscriptionType": "free",
            "apiRequests": 20,
            "apiRequestsDate": "2026-08-11",
            "dailyRateLimit": 20,
            "extraLimit": 0,
        },
        environ={"EODHD_API_TOKEN": "test-secret"},
    )

    assert result["status"] == "collecting"
    assert result["batch"]["success_tickers"] == universe[:15]
    assert calls == universe[:15]
    assert result["account"]["quota_reset_applied"] is True
    assert result["account"]["reported_used_calls"] == 20
    assert result["account"]["used_calls"] == 0


def test_deferred_mode_uses_yfinance_daily_without_calling_full_rest(
    tmp_path: Path,
    monkeypatch,
):
    settings, _universe, prices = _settings(tmp_path)
    today = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    one = prices[prices["ticker"].eq("T00")].tail(1).copy()
    one["date"] = today

    monkeypatch.setattr(
        RestEodProvider,
        "fetch_daily",
        lambda *_args, **_kwargs: pytest.fail(
            "full-universe REST must not run in deferred free-tier mode"
        ),
    )
    monkeypatch.setattr(
        YFinanceProvider,
        "fetch_daily",
        lambda *_args, **_kwargs: one.copy(),
    )

    frame, source = load_prices_from_provider(settings, tickers=["T00"])

    assert source == "yfinance_primary"
    assert len(frame) == 1
    assert frame.attrs["provider_failures"] == []
