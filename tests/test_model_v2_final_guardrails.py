from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pandas as pd

from src.config import load_settings
from src.model_v2.predict import infer_shadow_scores
from src.model_v2.promotion import apply_model_v2_rollout_selection
from src.model_v2.train import (
    _chronological_partition_indices,
    maybe_auto_train_model_v2,
)
from src.notify.telegram import build_model_v2_shadow_message


def _settings(tmp_path: Path):
    settings = load_settings("config/settings.json")
    settings.pipeline.active_modes = ["t1"]
    settings.model_v2.model_dir = str(tmp_path / "models")
    settings.model_v2.state_path = str(tmp_path / "model_v2_state.json")
    settings.model_v2.auto_train_enabled = True
    return settings


def test_inference_without_model_artifact_fails_closed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    candidates = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "mode": "t1",
                "score": 99.0,
                "atr_pct": 2.0,
                "entry": 1000.0,
                "stop": 950.0,
                "tp1": 1050.0,
            }
        ]
    )

    out, info = infer_shadow_scores(candidates, settings)

    assert info["status"] == "blocked"
    assert out.loc[0, "shadow_model_source"] == "unavailable"
    assert out.loc[0, "shadow_status"] == "blocked"
    assert bool(out.loc[0, "shadow_recommended"]) is False
    assert pd.isna(out.loc[0, "shadow_p_win"])
    assert pd.isna(out.loc[0, "shadow_expected_r"])


def test_missing_artifact_bypasses_recent_training_interval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path)
    Path(settings.model_v2.state_path).write_text(
        json.dumps(
            {
                "last_success_at": datetime.utcnow().isoformat(),
                "modes": {"t1": {"status": "trained"}},
            }
        ),
        encoding="utf-8",
    )
    trained = {"called": False, "saved": False}

    def fake_load_model_bundle(model_dir, mode):
        if trained["saved"]:
            return object(), {"trained_at": "now"}
        return None, {}

    def fake_training_rows(**kwargs):
        return pd.DataFrame({"y": [0, 1] * 100})

    def fake_train_one_mode(**kwargs):
        trained["called"] = True
        return object(), {"calibration": {"evaluated_on_holdout": True, "ece": 0.05}}

    def fake_save_model_bundle(**kwargs):
        trained["saved"] = True
        return {"artifact_path": "test.joblib", "metadata_path": "test.meta.json"}

    monkeypatch.setattr("src.model_v2.train.load_model_bundle", fake_load_model_bundle)
    monkeypatch.setattr("src.model_v2.train._HAS_OPTUNA", False)
    monkeypatch.setattr("src.model_v2.train._training_rows_for_mode", fake_training_rows)
    monkeypatch.setattr("src.model_v2.train._train_one_mode", fake_train_one_mode)
    monkeypatch.setattr("src.model_v2.train.save_model_bundle", fake_save_model_bundle)

    result = maybe_auto_train_model_v2(pd.DataFrame(), settings)

    assert trained["called"] is True
    assert result["status"] == "updated"
    assert result["artifact_check"]["forced_retrain"] is True
    assert result["artifact_check"]["ready"] is True


def test_rollout_never_selects_fallback_rows(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.risk.max_positions = 2
    shadow_path = tmp_path / "shadow.csv"
    pd.DataFrame(
        [
            {
                "ticker": "BAD",
                "mode": "t1",
                "score": 99.0,
                "shadow_p_win": 0.95,
                "shadow_expected_r": 1.2,
                "shadow_recommended": True,
                "shadow_model_source": "fallback",
            }
        ]
    ).to_csv(shadow_path, index=False)
    baseline = pd.DataFrame(
        [
            {"ticker": "AAA", "mode": "t1", "score": 90.0},
            {"ticker": "BBB", "mode": "t1", "score": 80.0},
        ]
    )

    _, selected, info = apply_model_v2_rollout_selection(
        filtered_combined=baseline,
        settings=settings,
        promotion_info={"rollout_pct": 30, "live_active": True},
        shadow_csv_path=str(shadow_path),
    )

    assert info["status"] == "blocked_no_valid_model_v2"
    assert "BAD" not in set(selected["ticker"])
    assert set(selected["ticker"]) == {"AAA", "BBB"}


def test_chronological_partitions_are_disjoint_and_purged() -> None:
    prepared = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=100, freq="D"),
            "y": [0, 1] * 50,
        }
    )

    fit_idx, cal_idx, test_idx = _chronological_partition_indices(
        prepared,
        gap_dates=5,
    )

    assert set(fit_idx).isdisjoint(cal_idx)
    assert set(fit_idx).isdisjoint(test_idx)
    assert set(cal_idx).isdisjoint(test_idx)
    fit_end = prepared.loc[fit_idx, "date"].max()
    cal_start = prepared.loc[cal_idx, "date"].min()
    cal_end = prepared.loc[cal_idx, "date"].max()
    test_start = prepared.loc[test_idx, "date"].min()
    assert (cal_start - fit_end).days > 5
    assert (test_start - cal_end).days > 5


def test_telegram_marks_non_model_candidates_as_blocked() -> None:
    payload = {
        "generated_at": "2026-07-17T01:00:00",
        "signals": [
            {
                "ticker": "TEST",
                "mode": "t1",
                "score": 99.0,
                "shadow_p_win": None,
                "shadow_expected_r": None,
                "shadow_recommended": False,
                "shadow_model_source": "unavailable",
                "entry": 1000.0,
                "stop": 950.0,
                "tp1": 1050.0,
            }
        ],
    }

    message = build_model_v2_shadow_message(payload)

    assert "Model status: BLOCKED" in message
    assert "Direkomendasikan V2 terverifikasi:" in message
    assert "Diblokir: 1 kandidat" in message
    assert "p(win)=0.0000" not in message
