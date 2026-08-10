from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import PriceQualitySettings
from src.ingest.quality import (
    build_split_adjusted_prices,
    classify_price_anomalies,
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
        anomaly_report_path=str(tmp_path / "anomalies.csv"),
        reconciliation_report_path=str(tmp_path / "reconciliation.json"),
        reconciliation_enabled=True,
        reconciliation_required=False,
    )
    pd.DataFrame(
        columns=["ticker", "effective_date", "action_type", "ratio", "status", "source"]
    ).to_csv(config.corporate_actions_path, index=False)

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
