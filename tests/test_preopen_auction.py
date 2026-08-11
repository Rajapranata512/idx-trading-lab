from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from src.config import load_settings
from src.notify import build_preopen_auction_message
from src.preopen.daemon import due_notification_phase
from src.preopen.data import DEPTH_COLUMNS, validate_preopen_snapshots
from src.preopen.features import build_preopen_features
from src.preopen.labels import LABEL_VERSION, build_preopen_labels
from src.preopen.pipeline import run_preopen_auction_shadow


class FixedClassifier:
    def __init__(self, probability: float) -> None:
        self.probability = float(probability)

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        positive = np.full(len(frame), self.probability, dtype=float)
        return np.column_stack([1.0 - positive, positive])


class FixedRegressor:
    def __init__(self, value: float) -> None:
        self.value = float(value)

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.full(len(frame), self.value, dtype=float)


def _snapshots(ticker: str = "BBCA") -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    timestamps = pd.date_range("2026-08-11T08:55:30+07:00", periods=14, freq="10s")
    for index, timestamp in enumerate(timestamps):
        row: dict[str, object] = {
            "timestamp": timestamp.isoformat(),
            "received_at": timestamp.isoformat(),
            "ticker": ticker,
            "previous_close": 100.0,
            "iep": 100.5 + (index * 0.05),
            "iev": 10000 + (index * 1000),
            "avg_daily_volume_20d": 1000000,
            "source": "licensed_test_feed",
            "rule_version": "IDX-II-A-2025",
        }
        for level in range(1, 6):
            row[f"bid_price_{level}"] = 100.0 - (level * 0.1)
            row[f"ask_price_{level}"] = 100.0 + (level * 0.1)
            row[f"bid_volume_{level}"] = 50000 - (level * 1000) + (index * 100)
            row[f"ask_volume_{level}"] = 30000 - (level * 500)
        rows.append(row)
    return pd.DataFrame(rows)


def _configure_preopen(tmp_path: Path):
    settings = load_settings("config/settings.json")
    cfg = settings.preopen_auction
    cfg.enabled = True
    cfg.shadow_only = True
    cfg.provider_name = "licensed_test_feed"
    cfg.data_license_confirmed = True
    cfg.retention_allowed = True
    cfg.snapshots_path = str(tmp_path / "snapshots.csv")
    cfg.features_path = str(tmp_path / "features.parquet")
    cfg.report_path = str(tmp_path / "report.json")
    cfg.scheduler_state_path = str(tmp_path / "scheduler.json")
    cfg.model_dir = str(tmp_path / "models")
    cfg.max_snapshot_age_seconds = 20
    return settings


def _write_model_bundle(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "models": {
            "open_up": FixedClassifier(0.80),
            "follow_up_15m": FixedClassifier(0.72),
            "follow_down_15m": FixedClassifier(0.12),
            "fake_gap_up_15m": FixedClassifier(0.10),
            "fake_gap_down_15m": FixedClassifier(0.08),
            "expected_return_15m_bps": FixedRegressor(95.0),
        }
    }
    joblib.dump(bundle, model_dir / "preopen_auction.joblib")
    metadata = {
        "model_version": "preopen-test-v1",
        "label_version": LABEL_VERSION,
        "rule_version": "IDX-II-A-2025",
        "decision_cutoff_time_local": "08:57:40",
        "feature_columns": ["snapshot_count", "iep_gap_bps", "weighted_depth_imbalance"],
        "calibrated": True,
        "evaluated_on_holdout": True,
        "ece_pct": 5.0,
        "oos_samples": 180,
        "walk_forward_folds": 5,
        "thresholds": {
            "p_open_up_min": 0.60,
            "p_open_down_min": 0.60,
            "p_follow_min": 0.60,
            "p_fake_max": 0.25,
            "p_fake_alert_min": 0.50,
            "expected_return_up_min_bps": 75.0,
            "expected_return_down_max_bps": -75.0,
        },
    }
    (model_dir / "preopen_auction.meta.json").write_text(json.dumps(metadata), encoding="utf-8")


def test_validate_and_build_preopen_features_uses_only_cutoff_data():
    snapshots = _snapshots()
    future = snapshots.iloc[-1].copy()
    future["timestamp"] = "2026-08-11T08:57:50+07:00"
    snapshots = pd.concat([snapshots, pd.DataFrame([future])], ignore_index=True)

    validated, report = validate_preopen_snapshots(
        snapshots,
        as_of="2026-08-11T08:57:40+07:00",
        max_snapshot_age_seconds=20,
    )
    features = build_preopen_features(
        validated,
        as_of="2026-08-11T08:57:40+07:00",
        max_snapshot_age_seconds=20,
    )

    assert report["ready"] is True
    assert validated["timestamp"].max() <= pd.Timestamp("2026-08-11T08:57:40+07:00")
    assert features.iloc[0]["snapshot_count"] == 14
    assert features.iloc[0]["data_ready"]
    assert features.iloc[0]["iep_gap_bps"] > 0
    assert features.iloc[0]["bid_ask_imbalance_l5"] > 0


def test_preopen_validation_requires_depth_when_configured():
    with pytest.raises(ValueError, match="Missing pre-open snapshot columns"):
        validate_preopen_snapshots(
            _snapshots()[["timestamp", "ticker", "previous_close", "iep", "iev"]],
            as_of="2026-08-11T08:57:40+07:00",
            require_market_depth=True,
        )


def test_build_preopen_labels_separates_open_and_follow_through():
    snapshots = _snapshots()[["timestamp", "ticker", "previous_close", "iep", "iev", "source", "rule_version"]]
    bars = pd.DataFrame(
        [
            {"timestamp": "2026-08-11T09:00:00+07:00", "ticker": "BBCA", "open": 102, "high": 103, "low": 101.5, "close": 102.8},
            {"timestamp": "2026-08-11T09:05:00+07:00", "ticker": "BBCA", "open": 102.8, "high": 104, "low": 102.5, "close": 103.8},
            {"timestamp": "2026-08-11T09:10:00+07:00", "ticker": "BBCA", "open": 103.8, "high": 105, "low": 103.5, "close": 104.8},
        ]
    )

    labels = build_preopen_labels(
        snapshots=snapshots,
        intraday_bars=bars,
        roundtrip_cost_bps=10,
        minimum_edge_bps=0,
    )

    assert len(labels) == 1
    assert labels.iloc[0]["label_version"] == LABEL_VERSION
    assert labels.iloc[0]["y_open_up"] == 1
    assert labels.iloc[0]["y_follow_up_15m"] == 1
    assert labels.iloc[0]["y_fake_gap_up_15m"] == 0


def test_pipeline_blocks_without_model_artifact(tmp_path: Path):
    settings = _configure_preopen(tmp_path)
    _snapshots().to_csv(settings.preopen_auction.snapshots_path, index=False)

    report = run_preopen_auction_shadow(settings, as_of="2026-08-11T08:57:40+07:00")

    assert report["status"] == "blocked"
    assert "model_artifact_missing" in report["block_reasons"]
    assert report["execution_status"] == "EXECUTION_DISABLED"
    assert Path(settings.preopen_auction.report_path).exists()


def test_pipeline_emits_shadow_watch_only_with_complete_model_contract(tmp_path: Path):
    settings = _configure_preopen(tmp_path)
    _snapshots().to_csv(settings.preopen_auction.snapshots_path, index=False)
    _write_model_bundle(Path(settings.preopen_auction.model_dir))

    report = run_preopen_auction_shadow(settings, as_of="2026-08-11T08:57:40+07:00")
    message = build_preopen_auction_message(report)

    assert report["status"] == "ready"
    assert report["summary"]["watch_up"] == 1
    assert report["signals"][0]["shadow_classification"] == "UP_FOLLOW_THROUGH"
    assert report["signals"][0]["final_decision"] is False
    assert report["signals"][0]["execution_authorized"] is False
    assert "Pantauan naik terverifikasi model" in message
    assert "BBCA" in message
    assert "bukan perintah beli/jual" in message


def test_scheduler_has_preliminary_and_final_phases_without_duplicates(tmp_path: Path):
    settings = _configure_preopen(tmp_path)

    assert due_notification_phase("2026-08-11T08:55:05+07:00", settings, {}) == "preliminary"
    state = {"session_date": "2026-08-11", "delivered_phases": ["preliminary"]}
    assert due_notification_phase("2026-08-11T08:55:30+07:00", settings, state) == ""
    attempted = {"session_date": "2026-08-11", "attempted_phases": ["preliminary"]}
    assert due_notification_phase("2026-08-11T08:55:30+07:00", settings, attempted) == ""
    assert due_notification_phase("2026-08-11T08:57:45+07:00", settings, state) == "final_preopen"
    state["delivered_phases"].append("final_preopen")
    assert due_notification_phase("2026-08-11T08:58:30+07:00", settings, state) == ""


def test_depth_contract_lists_all_five_levels():
    assert len(DEPTH_COLUMNS) == 20

def test_pipeline_blocks_malformed_model_metadata_without_crashing(tmp_path: Path):
    settings = _configure_preopen(tmp_path)
    _snapshots().to_csv(settings.preopen_auction.snapshots_path, index=False)
    model_dir = Path(settings.preopen_auction.model_dir)
    _write_model_bundle(model_dir)
    metadata_path = model_dir / "preopen_auction.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["ece_pct"] = "invalid"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    report = run_preopen_auction_shadow(settings, as_of="2026-08-11T08:57:40+07:00")

    assert report["status"] == "blocked"
    assert "preopen_model_contract_invalid" in report["block_reasons"]
    assert report["signals"][0]["shadow_classification"] == "NO_TRADE"

def test_fake_gap_label_requires_post_open_reversal():
    snapshots = _snapshots()[["timestamp", "ticker", "previous_close", "iep", "iev", "source", "rule_version"]]
    bars = pd.DataFrame(
        [
            {"timestamp": "2026-08-11T09:00:00+07:00", "ticker": "BBCA", "open": 102, "high": 102.5, "low": 101, "close": 101.2},
            {"timestamp": "2026-08-11T09:05:00+07:00", "ticker": "BBCA", "open": 101.2, "high": 101.4, "low": 99.5, "close": 99.8},
            {"timestamp": "2026-08-11T09:10:00+07:00", "ticker": "BBCA", "open": 99.8, "high": 100, "low": 98.5, "close": 99.0},
        ]
    )

    labels = build_preopen_labels(
        snapshots=snapshots,
        intraday_bars=bars,
        roundtrip_cost_bps=10,
        minimum_edge_bps=0,
        fake_reversal_bps=10,
    )

    assert labels.iloc[0]["y_open_up"] == 1
    assert labels.iloc[0]["y_follow_up_15m"] == 0
    assert labels.iloc[0]["y_fake_gap_up_15m"] == 1