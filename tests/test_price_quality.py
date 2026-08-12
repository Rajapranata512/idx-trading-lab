from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import PriceQualitySettings
from src.ingest.quality import (
    build_split_adjusted_prices,
    classify_price_anomalies,
    load_verified_price_events,
    reconcile_price_frames,
    run_price_quality_audit,
)


def _prices(closes: list[float]) -> pd.DataFrame:
    rows = []
    for index, close in enumerate(closes, start=1):
        rows.append(
            {
                "date": f"2026-01-{index:02d}",
                "ticker": "TEST",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000,
                "source": "test",
                "ingested_at": "2026-01-10T00:00:00",
            }
        )
    return pd.DataFrame(rows)


def _actions(status: str = "confirmed") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "effective_date": pd.Timestamp("2026-01-03"),
                "action_type": "stock_split",
                "ratio": 2.0,
                "status": status,
                "source": "IDX",
            }
        ]
    )


def _events(status: str = "confirmed") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "event_date": pd.Timestamp("2026-01-02"),
                "event_type": "index_rebalance",
                "status": status,
                "source": "https://example.test/index-review.pdf",
            }
        ]
    )


def test_split_adjustment_preserves_raw_and_adjusts_pre_event_rows():
    raw = _prices([100.0, 100.0, 50.0, 52.0])
    adjusted = build_split_adjusted_prices(raw, _actions())

    assert raw.loc[0, "close"] == 100.0
    assert adjusted.loc[0, "close"] == 50.0
    assert adjusted.loc[0, "volume"] == 2000.0
    assert adjusted.loc[0, "adjustment_factor"] == 2.0
    assert adjusted.loc[2, "close"] == 50.0
    assert adjusted.loc[2, "price_basis"] == "raw"


def test_recent_unresolved_jump_quarantines_ticker():
    anomalies, quarantined = classify_price_anomalies(
        prices=_prices([100.0, 150.0]),
        corporate_actions=pd.DataFrame(
            columns=["ticker", "effective_date", "action_type", "ratio", "status", "source"]
        ),
        threshold_pct=25.0,
        quarantine_days=3,
    )

    assert quarantined == ["TEST"]
    assert len(anomalies) == 1
    assert bool(anomalies.iloc[0]["active_quarantine"]) is True
    assert bool(anomalies.iloc[0]["resolved_by_action"]) is False


def test_confirmed_action_resolves_jump_without_quarantine():
    anomalies, quarantined = classify_price_anomalies(
        prices=_prices([100.0, 50.0, 52.0]),
        corporate_actions=_actions(),
        threshold_pct=25.0,
        quarantine_days=3,
    )

    assert quarantined == []
    assert len(anomalies) == 1
    assert bool(anomalies.iloc[0]["resolved_by_action"]) is True
    assert anomalies.iloc[0]["action_type"] == "stock_split"


def test_verified_event_resolves_exact_jump_without_adjusting_prices():
    raw = _prices([100.0, 150.0, 152.0])
    actions = pd.DataFrame(
        columns=["ticker", "effective_date", "action_type", "ratio", "status", "source"]
    )

    anomalies, quarantined = classify_price_anomalies(
        prices=raw,
        corporate_actions=actions,
        threshold_pct=25.0,
        quarantine_days=3,
        verified_events=_events(),
    )
    adjusted = build_split_adjusted_prices(raw, actions)

    assert quarantined == []
    assert len(anomalies) == 1
    assert bool(anomalies.iloc[0]["resolved"]) is True
    assert bool(anomalies.iloc[0]["resolved_by_action"]) is False
    assert bool(anomalies.iloc[0]["resolved_by_event"]) is True
    assert anomalies.iloc[0]["event_type"] == "index_rebalance"
    assert adjusted["close"].tolist() == raw["close"].tolist()
    assert adjusted["price_basis"].eq("raw").all()


def test_verified_event_loader_rejects_rows_without_traceable_source(tmp_path: Path):
    path = tmp_path / "events.csv"
    pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "event_date": "2026-01-02",
                "event_type": "index_rebalance",
                "status": "confirmed",
                "source": "",
            }
        ]
    ).to_csv(path, index=False)

    try:
        load_verified_price_events(path)
    except ValueError as exc:
        assert "invalid rows" in str(exc)
    else:
        raise AssertionError("Untraceable verified event must be rejected")


def test_price_reconciliation_fails_material_close_disagreement():
    primary = _prices([100.0, 100.0])
    reference = _prices([100.0, 90.0])

    result = reconcile_price_frames(
        primary=primary,
        reference=reference,
        lookback_sessions=5,
        max_close_diff_pct=1.0,
        max_mismatch_ratio=0.05,
    )

    assert result["status"] == "failed"
    assert result["mismatch_rows"] == 1
    assert result["mismatch_ratio"] == 0.5


def test_price_quality_audit_writes_separate_adjusted_and_reports(tmp_path: Path):
    config = PriceQualitySettings(
        adjusted_prices_path=str(tmp_path / "adjusted.csv"),
        corporate_actions_path=str(tmp_path / "actions.csv"),
        verified_price_events_path=str(tmp_path / "events.csv"),
        anomaly_report_path=str(tmp_path / "anomalies.csv"),
        reconciliation_report_path=str(tmp_path / "reconciliation.json"),
        reconciliation_details_path=str(tmp_path / "reconciliation_details.csv"),
        reconciliation_enabled=True,
        reconciliation_required=False,
    )
    pd.DataFrame(
        columns=["ticker", "effective_date", "action_type", "ratio", "status", "source"]
    ).to_csv(config.corporate_actions_path, index=False)
    pd.DataFrame(columns=["ticker", "event_date", "event_type", "status", "source"]).to_csv(
        config.verified_price_events_path,
        index=False,
    )

    result = run_price_quality_audit(
        prices=_prices([100.0, 101.0]),
        config=config,
        reconciliation_primary=_prices([100.0, 101.0]),
        reconciliation_reference=_prices([100.0, 101.0]),
        primary_source="rest",
        reference_source="independent",
    )

    assert Path(config.adjusted_prices_path).exists()
    assert Path(config.anomaly_report_path).exists()
    assert Path(config.reconciliation_report_path).exists()
    assert result["reconciliation"]["pass"] is True
    assert result["quarantined_tickers"] == []


def test_price_quality_audit_preserves_actionable_reconciliation_reason(tmp_path: Path):
    config = PriceQualitySettings(
        adjusted_prices_path=str(tmp_path / "adjusted.csv"),
        corporate_actions_path=str(tmp_path / "actions.csv"),
        verified_price_events_path=str(tmp_path / "events.csv"),
        anomaly_report_path=str(tmp_path / "anomalies.csv"),
        reconciliation_report_path=str(tmp_path / "reconciliation.json"),
        reconciliation_details_path=str(tmp_path / "reconciliation_details.csv"),
        reconciliation_enabled=True,
        reconciliation_required=False,
    )
    pd.DataFrame(
        columns=["ticker", "effective_date", "action_type", "ratio", "status", "source"]
    ).to_csv(config.corporate_actions_path, index=False)
    pd.DataFrame(columns=["ticker", "event_date", "event_type", "status", "source"]).to_csv(
        config.verified_price_events_path,
        index=False,
    )
    reason = "Primary provider fell back; configure an independent source"

    result = run_price_quality_audit(
        prices=_prices([100.0, 101.0]),
        config=config,
        reconciliation_primary=_prices([100.0, 101.0]),
        reconciliation_reference=None,
        primary_source="yfinance_fallback",
        reconciliation_unavailable_reason=reason,
    )

    assert result["reconciliation"]["status"] == "unavailable"
    assert result["reconciliation"]["pass"] is True
    assert result["reconciliation"]["message"] == reason
