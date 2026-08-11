from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.config import PriceQualitySettings, RestProviderSettings, load_settings
from src.ingest.providers.rest_provider import RestEodProvider
from src.ingest.quality import reconcile_price_frames, run_price_quality_audit
from src.ingest.reconciliation_evidence import record_price_reconciliation_evidence
from src.ingest.reconciliation_readiness import assess_eod_reconciliation_readiness


def _frame(session_date: str, tickers: tuple[str, ...] = ("BBCA", "TLKM")) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": session_date,
                "ticker": ticker,
                "open": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "close": 100.0 + index,
                "volume": 1_000_000,
                "source": "test",
                "ingested_at": f"{session_date}T10:30:00+00:00",
            }
            for index, ticker in enumerate(tickers)
        ]
    )


def _calendar(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "market": "IDX",
                "valid_from": "2026-01-01",
                "valid_until": "2026-12-31",
                "holidays": [],
            }
        ),
        encoding="utf-8",
    )


def _evidence_config(tmp_path: Path) -> PriceQualitySettings:
    calendar_path = tmp_path / "idx_calendar.json"
    _calendar(calendar_path)
    return PriceQualitySettings(
        reconciliation_evidence_enabled=True,
        reconciliation_evidence_dir=str(tmp_path / "evidence"),
        reconciliation_evidence_history_path=str(tmp_path / "history.json"),
        reconciliation_market_calendar_path=str(calendar_path),
        reconciliation_min_consecutive_sessions=5,
        reconciliation_evidence_retention_sessions=10,
    )


def _audit_config(tmp_path: Path, required: bool = False) -> PriceQualitySettings:
    config = _evidence_config(tmp_path)
    config.adjusted_prices_path = str(tmp_path / "adjusted.csv")
    config.corporate_actions_path = str(tmp_path / "actions.csv")
    config.verified_price_events_path = str(tmp_path / "events.csv")
    config.anomaly_report_path = str(tmp_path / "anomalies.csv")
    config.reconciliation_report_path = str(tmp_path / "reconciliation.json")
    config.reconciliation_details_path = str(tmp_path / "details.csv")
    config.reconciliation_required = required
    pd.DataFrame(
        columns=["ticker", "effective_date", "action_type", "ratio", "status", "source"]
    ).to_csv(config.corporate_actions_path, index=False)
    pd.DataFrame(
        columns=["ticker", "event_date", "event_type", "status", "source"]
    ).to_csv(config.verified_price_events_path, index=False)
    return config

def _summary(session_date: str) -> dict[str, object]:
    return {
        "status": "pass",
        "pass": True,
        "market_date": session_date,
        "session_dates": [session_date],
        "rows_expected": 2,
        "rows_compared": 2,
        "coverage_ratio": 1.0,
        "mismatch_rows": 0,
        "mismatch_ratio": 0.0,
        "primary_source": "rest",
        "reference_source": "yfinance_reconciliation",
    }


def _details(session_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": session_date,
                "ticker": ticker,
                "close_primary": 100.0,
                "close_reference": 100.0,
                "matched": True,
                "close_diff_pct": 0.0,
                "mismatch": False,
            }
            for ticker in ("BBCA", "TLKM")
        ]
    )


def test_reconciliation_coverage_counts_missing_reference_rows():
    primary = _frame("2026-08-03")
    reference = _frame("2026-08-03", tickers=("BBCA",))

    result = reconcile_price_frames(
        primary=primary,
        reference=reference,
        lookback_sessions=5,
        max_close_diff_pct=1.0,
        max_mismatch_ratio=0.05,
        min_coverage_ratio=0.95,
    )

    assert result["status"] == "failed"
    assert result["rows_expected"] == 2
    assert result["rows_compared"] == 1
    assert result["coverage_ratio"] == 0.5


def test_evidence_qualifies_after_five_complete_market_sessions_and_retry_is_idempotent(
    tmp_path: Path,
):
    config = _evidence_config(tmp_path)
    session_dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]
    result: dict[str, object] = {}

    for session_date in session_dates:
        frame = _frame(session_date)
        result = record_price_reconciliation_evidence(
            config=config,
            primary=frame,
            reference=frame.copy(),
            details=_details(session_date),
            reconciliation=_summary(session_date),
            active_unresolved_count=0,
        )

    assert result["qualified"] is True
    assert result["qualification"]["consecutive_passes"] == 5

    retry = record_price_reconciliation_evidence(
        config=config,
        primary=_frame(session_dates[-1]),
        reference=_frame(session_dates[-1]),
        details=_details(session_dates[-1]),
        reconciliation=_summary(session_dates[-1]),
        active_unresolved_count=0,
    )
    history = json.loads(Path(config.reconciliation_evidence_history_path).read_text(encoding="utf-8"))

    assert retry["qualified"] is True
    assert len(history["sessions"]) == 5
    assert Path(retry["session"]["evidence"]["primary_path"]).exists()
    assert retry["session"]["evidence"]["primary_sha256"]


def test_evidence_does_not_hide_a_missing_market_session(tmp_path: Path):
    config = _evidence_config(tmp_path)
    for session_date in ["2026-08-03", "2026-08-04", "2026-08-06", "2026-08-07", "2026-08-10"]:
        frame = _frame(session_date)
        result = record_price_reconciliation_evidence(
            config=config,
            primary=frame,
            reference=frame.copy(),
            details=_details(session_date),
            reconciliation=_summary(session_date),
            active_unresolved_count=0,
        )

    assert result["qualified"] is False
    assert "2026-08-05" in result["qualification"]["missing_session_dates"]


def test_price_quality_audit_writes_details_and_collecting_evidence(tmp_path: Path):
    config = _audit_config(tmp_path)

    primary = _frame("2026-08-03")

    result = run_price_quality_audit(
        prices=primary,
        config=config,
        reconciliation_primary=primary,
        reconciliation_reference=primary.copy(),
        primary_source="rest",
        reference_source="yfinance_reconciliation",
    )

    assert result["reconciliation"]["status"] == "pass"
    assert result["reconciliation_evidence"]["status"] == "collecting"
    assert Path(config.reconciliation_details_path).exists()
    details = pd.read_csv(config.reconciliation_details_path)
    assert len(details) == 2
    assert details["matched"].all()


def test_required_unavailable_reconciliation_is_fail_closed(tmp_path: Path):
    config = _audit_config(tmp_path, required=True)
    primary = _frame("2026-08-03")

    result = run_price_quality_audit(
        prices=primary,
        config=config,
        reconciliation_primary=primary,
        reconciliation_reference=None,
        primary_source="rest",
        reconciliation_unavailable_reason="reference unavailable",
    )

    assert result["reconciliation"]["status"] == "unavailable"
    assert result["reconciliation"]["pass"] is False


def test_material_mismatch_is_blocking_even_before_required_enforcement(tmp_path: Path):
    config = _audit_config(tmp_path, required=False)
    primary = _frame("2026-08-03", tickers=("BBCA",))
    reference = primary.copy()
    reference["close"] = 80.0

    result = run_price_quality_audit(
        prices=primary,
        config=config,
        reconciliation_primary=primary,
        reconciliation_reference=reference,
        primary_source="rest",
        reference_source="yfinance_reconciliation",
    )

    assert result["reconciliation"]["status"] == "failed"
    assert result["reconciliation"]["pass"] is False
    assert result["reconciliation"]["mismatch_ratio"] == 1.0

def test_readiness_reports_only_secret_name_and_never_secret_value():
    settings = load_settings("config/settings.json")

    blocked = assess_eod_reconciliation_readiness(settings, environ={})
    ready = assess_eod_reconciliation_readiness(
        settings,
        environ={"EODHD_API_TOKEN": "super-secret-value"},
    )

    assert blocked["ready"] is False
    assert blocked["missing_environment_variables"] == ["EODHD_API_TOKEN"]
    assert ready["ready"] is True
    assert "super-secret-value" not in json.dumps(ready)


def test_rest_provider_rejects_missing_environment_before_http(monkeypatch):
    settings = RestProviderSettings(
        base_url_template="https://example.com/eod/{ticker}",
        query_params={"api_token": "${MISSING_TEST_TOKEN}"},
        column_mapping={
            "date": "date",
            "ticker": "ticker",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        },
    )
    provider = RestEodProvider(settings)
    monkeypatch.delenv("MISSING_TEST_TOKEN", raising=False)
    monkeypatch.setattr(
        provider,
        "_request_json",
        lambda url: pytest.fail("HTTP must not be attempted when credential is missing"),
    )

    with pytest.raises(RuntimeError, match="MISSING_TEST_TOKEN"):
        provider.fetch_daily(tickers=["BBCA"])