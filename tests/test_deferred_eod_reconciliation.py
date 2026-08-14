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
    assert first["rollout"]["successful_dates"] == ["2026-08-12"]
    assert first["rollout"]["successful_date_count"] == 1
    assert first["rollout"]["remaining_successful_dates"] == 2
    assert first["rollout"]["completed_tickers"] == 15
    assert first["rollout"]["remaining_tickers"] == 30
    assert first["rollout"]["ticker_progress_ratio"] == 0.333333
    assert first["rollout"]["ready_for_deferred_audit"] is False
    assert len(calls) == 15
    assert second["batch"]["idempotent_skip"] is True
    assert second["batch"]["selected_tickers"] == []
    assert second["account"]["required_calls"] == 0
    assert second["rollout"]["successful_dates"] == ["2026-08-12"]
    persisted_report = json.loads(
        Path(
            settings.data.price_quality.deferred_eod_reconciliation.report_path
        ).read_text(encoding="utf-8")
    )
    state = json.loads(
        Path(
            settings.data.price_quality.deferred_eod_reconciliation.state_path
        ).read_text(encoding="utf-8")
    )
    assert persisted_report["batch"]["success_tickers"] == universe[:15]
    assert persisted_report["schema_version"] == 2
    assert persisted_report["batch"]["idempotent_skip"] is False
    assert persisted_report["rollout"]["successful_date_count"] == 1
    assert persisted_report["rollout"]["completed_tickers"] == 15
    assert persisted_report["last_checked_at"] == second["generated_at"]
    assert len(state["runs"]) == 2
    assert state["runs"][0]["success_tickers"] == universe[:15]
    assert state["runs"][1]["idempotent_skip"] is True
    assert state["last_successful_batch"]["completed_current_cycle"] == 15
    assert state["schema_version"] == 2
    assert "test-secret" not in json.dumps(first)


def test_deferred_collection_reconstructs_v1_success_progress_without_provider_calls(
    tmp_path: Path,
):
    settings, universe, _prices = _settings(tmp_path)
    state_path = Path(
        settings.data.price_quality.deferred_eod_reconciliation.state_path
    )
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cycle": 1,
                "completed_cycle_tickers": universe[:15],
                "last_success_date": "2026-08-12",
                "runs": [],
            }
        ),
        encoding="utf-8",
    )

    result = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 12, 12, tzinfo=timezone.utc),
        fetcher=lambda *_args: pytest.fail("migration retry must not fetch tickers"),
        account_fetcher=lambda *_args: pytest.fail(
            "migration retry must not call account endpoint"
        ),
        environ={"EODHD_API_TOKEN": "test-secret"},
    )
    migrated_state = json.loads(state_path.read_text(encoding="utf-8"))
    recovered = result["last_successful_batch"]

    assert result["batch"]["idempotent_skip"] is True
    assert result["account"]["required_calls"] == 0
    assert migrated_state["schema_version"] == 2
    assert recovered["run_date"] == "2026-08-12"
    assert recovered["cycle"] == 1
    assert recovered["success_tickers"] == []
    assert recovered["completed_cycle_tickers"] == universe[:15]
    assert recovered["completed_current_cycle"] == 15
    assert recovered["cycle_completed"] is False
    assert recovered["reconstructed_from_state"] is True
    assert result["rollout"]["successful_dates"] == ["2026-08-12"]
    assert result["rollout"]["successful_date_count"] == 1
    assert result["rollout"]["remaining_successful_dates"] == 2
    assert result["rollout"]["completed_tickers"] == 15


def test_v1_migration_preserves_first_success_date_through_full_rollout(
    tmp_path: Path,
):
    settings, universe, prices = _settings(tmp_path)
    state_path = Path(
        settings.data.price_quality.deferred_eod_reconciliation.state_path
    )
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cycle": 1,
                "completed_cycle_tickers": universe[:15],
                "last_success_date": "2026-08-12",
                "runs": [],
            }
        ),
        encoding="utf-8",
    )

    collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 12, 12, tzinfo=timezone.utc),
        fetcher=lambda *_args: pytest.fail("migration retry must not fetch tickers"),
        account_fetcher=lambda *_args: pytest.fail(
            "migration retry must not call account endpoint"
        ),
        environ={"EODHD_API_TOKEN": "test-secret"},
    )

    def fetcher(ticker: str, _start: str, _end: str) -> pd.DataFrame:
        return prices[prices["ticker"].eq(ticker)].copy()

    second = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 13, 10, tzinfo=timezone.utc),
        fetcher=fetcher,
        account_fetcher=_account_payload,
        environ={"EODHD_API_TOKEN": "test-secret"},
    )
    final = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 14, 10, tzinfo=timezone.utc),
        fetcher=fetcher,
        account_fetcher=_account_payload,
        environ={"EODHD_API_TOKEN": "test-secret"},
    )

    assert second["rollout"]["successful_dates"] == [
        "2026-08-12",
        "2026-08-13",
    ]
    assert second["rollout"]["successful_date_count"] == 2
    assert second["rollout"]["completed_tickers"] == 30
    assert final["rollout"]["successful_dates"] == [
        "2026-08-12",
        "2026-08-13",
        "2026-08-14",
    ]
    assert final["rollout"]["successful_date_count"] == 3
    assert final["rollout"]["completed_tickers"] == 45
    assert final["rollout"]["ready_for_deferred_audit"] is True
    assert final["rollout"]["final_execution_eligible"] is False

    incomplete_rollout = dict(final["rollout"])
    incomplete_rollout.update(
        {
            "status": "collecting",
            "successful_dates": ["2026-08-13", "2026-08-14"],
            "successful_date_count": 2,
            "remaining_successful_dates": 1,
            "ready_for_deferred_audit": False,
        }
    )
    completed_state = json.loads(state_path.read_text(encoding="utf-8"))
    completed_state["last_completed_rollout"] = incomplete_rollout
    state_path.write_text(json.dumps(completed_state), encoding="utf-8")
    report_path = Path(
        settings.data.price_quality.deferred_eod_reconciliation.report_path
    )
    incomplete_report = json.loads(report_path.read_text(encoding="utf-8"))
    incomplete_report["rollout"] = incomplete_rollout
    report_path.write_text(json.dumps(incomplete_report), encoding="utf-8")

    recovered = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 14, 11, tzinfo=timezone.utc),
        fetcher=lambda *_args: pytest.fail("recovery retry must not fetch tickers"),
        account_fetcher=lambda *_args: pytest.fail(
            "recovery retry must not call account endpoint"
        ),
        environ={"EODHD_API_TOKEN": "test-secret"},
    )
    recovered_state = json.loads(state_path.read_text(encoding="utf-8"))
    recovered_report = json.loads(report_path.read_text(encoding="utf-8"))

    assert recovered["batch"]["idempotent_skip"] is True
    assert recovered["account"]["required_calls"] == 0
    assert recovered["rollout"]["successful_date_count"] == 3
    assert recovered["rollout"]["ready_for_deferred_audit"] is True
    assert recovered_state["last_completed_rollout"]["successful_date_count"] == 3
    assert recovered_report["rollout"]["successful_date_count"] == 3
    assert recovered_report["rollout"]["completed_tickers"] == 45


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
    assert outputs[1]["rollout"]["successful_dates"] == [
        "2026-08-12",
        "2026-08-13",
    ]
    assert outputs[1]["rollout"]["successful_date_count"] == 2
    assert outputs[1]["rollout"]["remaining_successful_dates"] == 1
    assert outputs[1]["rollout"]["completed_tickers"] == 30
    assert outputs[1]["rollout"]["ticker_progress_ratio"] == 0.666667
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
    assert final["batch"]["cycle"] == 1
    assert final["batch"]["next_cycle"] == 2
    assert final["batch"]["cycle_completed"] is True
    assert final["batch"]["completed_current_cycle"] == 45
    assert final["last_successful_batch"]["cycle"] == 1
    assert final["last_successful_batch"]["cycle_completed"] is True
    assert final["rollout"]["status"] == "complete"
    assert final["rollout"]["successful_dates"] == [
        "2026-08-12",
        "2026-08-13",
        "2026-08-14",
    ]
    assert final["rollout"]["successful_date_count"] == 3
    assert final["rollout"]["remaining_successful_dates"] == 0
    assert final["rollout"]["completed_tickers"] == 45
    assert final["rollout"]["remaining_tickers"] == 0
    assert final["rollout"]["ticker_progress_ratio"] == 1.0
    assert final["rollout"]["ready_for_deferred_audit"] is True

    retry = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 14, 11, tzinfo=timezone.utc),
        fetcher=lambda *_args: pytest.fail("completed-day retry must not fetch tickers"),
        account_fetcher=lambda *_args: pytest.fail(
            "completed-day retry must not call account endpoint"
        ),
        environ={"EODHD_API_TOKEN": "test-secret"},
    )
    persisted_report = json.loads(
        Path(
            settings.data.price_quality.deferred_eod_reconciliation.report_path
        ).read_text(encoding="utf-8")
    )
    state = json.loads(
        Path(
            settings.data.price_quality.deferred_eod_reconciliation.state_path
        ).read_text(encoding="utf-8")
    )
    assert retry["batch"]["idempotent_skip"] is True
    assert retry["last_successful_batch"]["cycle_completed"] is True
    assert persisted_report["batch"]["cycle"] == 1
    assert persisted_report["batch"]["completed_current_cycle"] == 45
    assert persisted_report["batch"]["cycle_completed"] is True
    assert persisted_report["rollout"]["status"] == "complete"
    assert persisted_report["rollout"]["successful_date_count"] == 3
    assert state["cycle"] == 2
    assert state["last_completed_cycle"] == 1
    assert state["completed_cycle_tickers"] == []
    assert len(state["runs"]) == 4
    assert state["last_completed_rollout"]["status"] == "complete"
    assert state["last_completed_rollout"]["successful_date_count"] == 3

    next_cycle = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 15, 10, tzinfo=timezone.utc),
        fetcher=fetcher,
        account_fetcher=_account_payload,
        environ={"EODHD_API_TOKEN": "test-secret"},
    )
    next_state = json.loads(
        Path(
            settings.data.price_quality.deferred_eod_reconciliation.state_path
        ).read_text(encoding="utf-8")
    )
    assert next_cycle["batch"]["cycle"] == 2
    assert next_cycle["batch"]["completed_current_cycle"] == 15
    assert next_cycle["rollout"]["successful_dates"] == ["2026-08-15"]
    assert next_cycle["rollout"]["successful_date_count"] == 1
    assert next_cycle["rollout"]["remaining_successful_dates"] == 2
    assert next_cycle["rollout"]["completed_tickers"] == 15
    assert next_state["last_completed_rollout"]["cycle"] == 1
    assert next_state["last_completed_rollout"]["status"] == "complete"

    cache = pd.read_csv(
        settings.data.price_quality.deferred_eod_reconciliation.cache_path
    )
    details = pd.read_csv(
        settings.data.price_quality.deferred_eod_reconciliation.details_path
    )
    assert cache["ticker"].nunique() == 45
    assert len(details) == 45 * 5


def test_same_day_retry_refreshes_persisted_audit_without_provider_calls(
    tmp_path: Path,
):
    settings, universe, prices = _settings(tmp_path)

    def fetcher(ticker: str, _start: str, _end: str) -> pd.DataFrame:
        return prices[prices["ticker"].eq(ticker)].copy()

    for day in [12, 13, 14]:
        collect_deferred_eod_reconciliation(
            settings,
            now=datetime(2026, 8, day, 10, tzinfo=timezone.utc),
            fetcher=fetcher,
            account_fetcher=_account_payload,
            environ={"EODHD_API_TOKEN": "test-secret"},
        )

    report_path = Path(
        settings.data.price_quality.deferred_eod_reconciliation.report_path
    )
    initial_report = json.loads(report_path.read_text(encoding="utf-8"))
    initial_generated_at = initial_report["generated_at"]
    canonical_path = Path(settings.data.canonical_prices_path)
    canonical = pd.read_csv(canonical_path)
    target = canonical["ticker"].eq(universe[0]) & canonical["date"].eq("2026-08-11")
    ohlc_columns = ["open", "high", "low", "close"]
    original_ohlc = canonical.loc[target, ohlc_columns].copy()
    canonical.loc[target, ohlc_columns] *= 1.20
    canonical.to_csv(canonical_path, index=False)

    stale = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 14, 11, tzinfo=timezone.utc),
        fetcher=lambda *_args: pytest.fail("same-day retry must not fetch tickers"),
        account_fetcher=lambda *_args: pytest.fail(
            "same-day retry must not call account endpoint"
        ),
        environ={"EODHD_API_TOKEN": "test-secret"},
    )
    stale_report = json.loads(report_path.read_text(encoding="utf-8"))

    assert stale["batch"]["idempotent_skip"] is True
    assert stale["account"]["required_calls"] == 0
    assert stale["audit"]["mismatch_rows"] == 1
    assert stale_report["audit"] == stale["audit"]
    assert stale_report["status"] == stale["status"]
    assert stale_report["generated_at"] == initial_generated_at
    assert stale_report["last_checked_at"] == stale["generated_at"]

    canonical.loc[target, ohlc_columns] = original_ohlc.to_numpy()
    canonical.to_csv(canonical_path, index=False)
    corrected = collect_deferred_eod_reconciliation(
        settings,
        now=datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
        fetcher=lambda *_args: pytest.fail("same-day retry must not fetch tickers"),
        account_fetcher=lambda *_args: pytest.fail(
            "same-day retry must not call account endpoint"
        ),
        environ={"EODHD_API_TOKEN": "test-secret"},
    )
    corrected_report = json.loads(report_path.read_text(encoding="utf-8"))

    assert corrected["audit"]["mismatch_rows"] == 0
    assert corrected_report["audit"] == corrected["audit"]
    assert corrected_report["research_evidence_eligible"] is True
    assert corrected_report["generated_at"] == initial_generated_at
    assert corrected_report["last_checked_at"] == corrected["generated_at"]


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
