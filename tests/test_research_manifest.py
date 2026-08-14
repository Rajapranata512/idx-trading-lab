from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.config import load_settings
from src.features.contract import FEATURE_OUTPUT_COLUMNS
from src.ingest.research_manifest import (
    ResearchManifestError,
    build_research_dataset_manifest,
    validate_research_dataset_manifest_file,
)


SOURCE_REVISION = "a" * 40


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _fixture(tmp_path: Path):
    settings = load_settings("config/settings.json")
    settings.data.canonical_prices_path = str(tmp_path / "data/raw/prices.csv")
    settings.data.universe_csv_path = str(tmp_path / "data/reference/universe.csv")
    settings.data.research_manifest_path = str(
        tmp_path / "reports/research_dataset_manifest.json"
    )
    settings.data.universe_auto_update.history_path = str(
        tmp_path / "data/reference/universe_history.csv"
    )
    quality = settings.data.price_quality
    quality.adjusted_prices_path = str(tmp_path / "data/processed/adjusted.csv")
    quality.corporate_actions_path = str(
        tmp_path / "data/reference/corporate_actions.csv"
    )
    quality.verified_price_events_path = str(
        tmp_path / "data/reference/verified_price_events.csv"
    )
    deferred = quality.deferred_eod_reconciliation
    deferred.cache_path = str(tmp_path / "data/raw/deferred.csv")
    deferred.report_path = str(tmp_path / "reports/deferred.json")
    deferred.details_path = str(tmp_path / "reports/deferred_details.csv")

    price_row = {
        "date": "2026-08-14",
        "ticker": "TEST",
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1000000,
        "source": "test",
        "ingested_at": "2026-08-14T10:00:00+00:00",
    }
    _write_csv(Path(settings.data.canonical_prices_path), [price_row])
    _write_csv(Path(quality.adjusted_prices_path), [price_row])
    _write_csv(
        Path(settings.data.universe_csv_path),
        [{"ticker": "TEST", "as_of": "2026-08-14"}],
    )
    _write_csv(
        Path(settings.data.universe_auto_update.history_path),
        [
            {
                "ticker": "TEST",
                "index": "LQ45",
                "effective_from": "2026-08-01",
                "effective_to": "2027-01-31",
            }
        ],
    )
    _write_csv(
        Path(quality.corporate_actions_path),
        [
            {
                "ticker": "TEST",
                "date": "2026-01-01",
                "action_type": "stock_split",
                "ratio": 2.0,
            }
        ],
    )
    _write_csv(
        Path(quality.verified_price_events_path),
        [
            {
                "ticker": "TEST",
                "date": "2026-02-01",
                "event_type": "index_rebalance",
            }
        ],
    )
    _write_csv(
        tmp_path / "data/reference/price_reconciliation_incidents.csv",
        [{"market_date": "2026-08-14", "ticker": "TEST", "status": "resolved"}],
    )
    _write_csv(Path(deferred.cache_path), [price_row])
    _write_csv(
        Path(deferred.details_path),
        [
            {
                "date": "2026-08-14",
                "ticker": "TEST",
                "close_primary": 101.0,
                "close_reference": 101.0,
                "mismatch": False,
            }
        ],
    )
    Path(deferred.report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(deferred.report_path).write_text(
        json.dumps(
            {
                "status": "pass",
                "final_execution_eligible": False,
            }
        ),
        encoding="utf-8",
    )

    feature_row = {column: 0.0 for column in FEATURE_OUTPUT_COLUMNS}
    feature_row.update(
        {
            "date": "2026-08-14",
            "ticker": "TEST",
            "source": "test",
            "ingested_at": "2026-08-14T10:00:00+00:00",
        }
    )
    features_path = tmp_path / "data/processed/features.parquet"
    features_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([feature_row], columns=FEATURE_OUTPUT_COLUMNS).to_parquet(
        features_path,
        index=False,
    )
    return settings


def test_manifest_is_deterministic_and_validates_all_hashes(tmp_path: Path):
    settings = _fixture(tmp_path)

    first = build_research_dataset_manifest(
        settings,
        root=tmp_path,
        source_revision=SOURCE_REVISION,
    )
    manifest_path = Path(settings.data.research_manifest_path)
    first_bytes = manifest_path.read_bytes()
    second = build_research_dataset_manifest(
        settings,
        root=tmp_path,
        source_revision=SOURCE_REVISION,
    )
    validation = validate_research_dataset_manifest_file(
        settings,
        root=tmp_path,
    )

    assert first == second
    assert manifest_path.read_bytes() == first_bytes
    assert validation["status"] == "pass"
    assert validation["dataset_id"] == first["dataset_id"]
    assert validation["artifact_count"] == 11
    assert first["safety"]["final_execution_eligible"] is False


def test_manifest_validation_detects_artifact_hash_drift(tmp_path: Path):
    settings = _fixture(tmp_path)
    build_research_dataset_manifest(
        settings,
        root=tmp_path,
        source_revision=SOURCE_REVISION,
    )

    canonical_path = Path(settings.data.canonical_prices_path)
    canonical_path.write_text(
        canonical_path.read_text(encoding="utf-8") + chr(10),
        encoding="utf-8",
    )

    with pytest.raises(ResearchManifestError, match="hash mismatch"):
        validate_research_dataset_manifest_file(settings, root=tmp_path)


def test_manifest_build_fails_when_required_artifact_is_missing(tmp_path: Path):
    settings = _fixture(tmp_path)
    Path(settings.data.price_quality.corporate_actions_path).unlink()

    with pytest.raises(ResearchManifestError, match="Required research artifact"):
        build_research_dataset_manifest(
            settings,
            root=tmp_path,
            source_revision=SOURCE_REVISION,
        )


def test_manifest_build_rejects_undeclared_feature_column(tmp_path: Path):
    settings = _fixture(tmp_path)
    features_path = tmp_path / "data/processed/features.parquet"
    features = pd.read_parquet(features_path)
    features["future_leak"] = 1.0
    features.to_parquet(features_path, index=False)

    with pytest.raises(ResearchManifestError, match="Feature contract mismatch"):
        build_research_dataset_manifest(
            settings,
            root=tmp_path,
            source_revision=SOURCE_REVISION,
        )
