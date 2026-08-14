from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.config import load_settings
from src.model_v2.calibration import calibrate_model
from src.model_v2.meta_filter import (
    annotate_historical_bayesian_edge,
    apply_bayesian_ticker_edge_filter,
    build_bayesian_ticker_edge_profile,
)
from src.model_v2.promotion import apply_model_v2_rollout_selection
from src.model_v2.train import (
    WALK_FORWARD_EVIDENCE_ROLE,
    WALK_FORWARD_PROMOTION_ELIGIBLE,
    _build_logreg_pipeline,
    _build_walk_forward_challengers,
    _probability_threshold_diagnostics,
    _select_fold_challenger,
    _training_experiment_contract,
    _walk_forward_date_splits,
)


def test_auto_calibration_fits_posthoc_model_on_calibration_window() -> None:
    rng = np.random.RandomState(7)
    x = pd.DataFrame({"a": rng.normal(size=500), "b": rng.normal(size=500)})
    logits = (x["a"] * 0.8) - (x["b"] * 0.25)
    y = (logits + rng.normal(scale=0.7, size=len(x)) > 0).astype(int).to_numpy()
    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=300)),
        ]
    )
    pipeline.fit(x.iloc[:300], y[:300])

    calibrated = calibrate_model(
        pipeline,
        x.iloc[300:],
        y[300:],
        method="auto",
    )

    assert calibrated.calibrator is not None
    assert calibrated.calibration_method in {"sigmoid", "isotonic"}
    assert calibrated.selection_diagnostics["selection_strategy"] == "temporal_calibration_holdout"
    probabilities = calibrated.predict_proba(x.iloc[:10])
    assert probabilities.shape == (10, 2)
    assert np.allclose(probabilities.sum(axis=1), 1.0)


def test_walk_forward_splits_are_purged_and_have_five_folds() -> None:
    prepared = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=500, freq="D"),
            "ticker": ["TEST"] * 500,
        }
    )

    splits = _walk_forward_date_splits(prepared, n_splits=5, gap_dates=10)

    assert len(splits) == 5
    for fit_idx, calibration_idx, test_idx in splits:
        assert set(fit_idx).isdisjoint(calibration_idx)
        assert set(fit_idx).isdisjoint(test_idx)
        assert set(calibration_idx).isdisjoint(test_idx)
        fit_end = prepared.loc[fit_idx, "date"].max()
        calibration_start = prepared.loc[calibration_idx, "date"].min()
        calibration_end = prepared.loc[calibration_idx, "date"].max()
        test_start = prepared.loc[test_idx, "date"].min()
        assert (calibration_start - fit_end).days > 10
        assert (test_start - calibration_end).days > 10


def test_probability_diagnostics_explain_zero_trade_fold() -> None:
    diagnostics = _probability_threshold_diagnostics(
        pd.Series([0.12, 0.31, np.nan, np.inf, 0.519]),
        threshold=0.52,
    )

    assert diagnostics["input_rows"] == 5
    assert diagnostics["valid_rows"] == 3
    assert diagnostics["non_finite_rows"] == 2
    assert diagnostics["selected_rows"] == 0
    assert diagnostics["selected_rate_pct"] == 0.0
    assert diagnostics["max"] == 0.519
    assert diagnostics["abstention_reason"] == "all_probabilities_below_threshold"


def test_probability_diagnostics_report_threshold_coverage() -> None:
    diagnostics = _probability_threshold_diagnostics(
        [0.4, 0.52, 0.7, 0.8],
        threshold=0.52,
    )

    assert diagnostics["selected_rows"] == 3
    assert diagnostics["selected_rate_pct"] == 75.0
    assert diagnostics["median"] == 0.61
    assert diagnostics["abstention_reason"] == "selected"


def test_fold_challenger_selection_never_reads_outer_rows(monkeypatch) -> None:
    fit_index = pd.Index([10, 11, 12, 13])
    x_fit = pd.DataFrame({"score": [1.0, 2.0, 3.0, 4.0]}, index=fit_index)
    y_fit = pd.Series([0, 1, 0, 1], index=fit_index)
    dates_fit = pd.Series(pd.date_range("2026-01-01", periods=4), index=fit_index)
    weights = pd.Series([1.0] * 4, index=fit_index)
    observed_indices: list[list[int]] = []

    def fake_time_cv_auc(pipeline, X, y, dates, **kwargs):
        observed_indices.append(list(X.index))
        class_weight = pipeline.named_steps["clf"].class_weight
        return 0.6 if class_weight == "balanced" else 0.55

    monkeypatch.setattr("src.model_v2.train._time_cv_auc", fake_time_cv_auc)
    name, _, diagnostics = _select_fold_challenger(
        challengers=[
            ("logreg_balanced_full", _build_logreg_pipeline("balanced")),
            ("logreg_unweighted_full", _build_logreg_pipeline(None)),
        ],
        x_fit=x_fit,
        y_fit=y_fit,
        dates_fit=dates_fit,
        sample_weight_fit=weights,
        gap_dates=1,
        tree_min_cv_auc_gain=0.02,
    )

    assert name == "logreg_balanced_full"
    assert observed_indices == [list(fit_index), list(fit_index)]
    assert diagnostics["outer_test_used_for_selection"] is False
    assert diagnostics["selected_cv_auc"] == 0.6


def test_walk_forward_challengers_include_bounded_feature_ablations() -> None:
    challengers = dict(_build_walk_forward_challengers())

    assert "logreg_balanced_full" in challengers
    assert "logreg_unweighted_full" in challengers
    assert "logreg_balanced_no_raw_levels" in challengers
    assert "logreg_balanced_no_score" in challengers
    assert (
        getattr(
            challengers["logreg_balanced_no_raw_levels"],
            "_model_v2_feature_contract",
        )
        == "model-v2-no-raw-levels-v1"
    )


def test_challenger_comparison_is_never_promotion_evidence() -> None:
    assert WALK_FORWARD_EVIDENCE_ROLE == "nested_challenger_selection_research"
    assert WALK_FORWARD_PROMOTION_ELIGIBLE is False


def test_training_experiment_identity_is_order_stable_and_data_sensitive() -> None:
    settings = load_settings("config/settings.json")
    frame = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-01"],
            "ticker": ["BBB", "AAA"],
            "score": [90.0, 95.0],
            "y": [0, 1],
            "net_return": [-0.2, 0.4],
        }
    )
    challengers = _build_walk_forward_challengers()

    first = _training_experiment_contract(frame, "t1", settings, 1, challengers)
    reordered = _training_experiment_contract(
        frame.iloc[::-1].reset_index(drop=True),
        "t1",
        settings,
        1,
        challengers,
    )
    changed = frame.copy()
    changed.loc[0, "y"] = 1
    changed_contract = _training_experiment_contract(
        changed,
        "t1",
        settings,
        1,
        challengers,
    )

    assert first["experiment_id"] == reordered["experiment_id"]
    assert first["training_frame_sha256"] == reordered["training_frame_sha256"]
    assert first["experiment_id"] != changed_contract["experiment_id"]


def test_bayesian_ticker_edge_waits_for_samples_then_blocks(tmp_path: Path) -> None:
    settings = load_settings("config/settings.json")
    settings.model_v2.ticker_edge_profile_path = str(tmp_path / "ticker_edge.csv")
    settings.model_v2.ticker_edge_min_samples = 3
    settings.model_v2.ticker_edge_prior_strength = 5.0
    settings.model_v2.ticker_edge_min_shrunk_expectancy_r = -0.05
    trades = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=6, freq="D"),
            "ticker": ["BAD"] * 6,
            "mode": ["t1"] * 6,
            "realized_r": [-1.0, -0.8, -0.7, -0.9, -0.6, -0.5],
        }
    )

    historical = annotate_historical_bayesian_edge(trades, settings=settings)
    profile = build_bayesian_ticker_edge_profile(trades, settings=settings)
    live = apply_bayesian_ticker_edge_filter(
        pd.DataFrame(
            [
                {"ticker": "BAD", "mode": "t1"},
                {"ticker": "NEW", "mode": "t1"},
            ]
        ),
        settings=settings,
        profile=profile,
    )

    assert "block" not in set(historical.iloc[:3]["meta_ticker_edge_action"])
    assert "block" in set(historical.iloc[3:]["meta_ticker_edge_action"])
    assert live.loc[live["ticker"] == "BAD", "meta_ticker_edge_action"].iloc[0] == "block"
    assert live.loc[live["ticker"] == "NEW", "meta_ticker_edge_action"].iloc[0] == "watch"


def test_rollout_can_promote_t1_while_swing_stays_shadow(tmp_path: Path) -> None:
    settings = load_settings("config/settings.json")
    settings.pipeline.active_modes = ["t1", "swing"]
    settings.risk.max_positions = 3
    settings.model_v2.ticker_edge_profile_path = str(tmp_path / "missing_profile.csv")
    baseline = pd.DataFrame(
        [
            {"ticker": "AAA", "mode": "t1", "score": 99.0},
            {"ticker": "BBB", "mode": "swing", "score": 90.0},
            {"ticker": "CCC", "mode": "t1", "score": 95.0},
        ]
    )
    shadow_path = tmp_path / "shadow.csv"
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "mode": "t1",
                "score": 99.0,
                "shadow_p_win": 0.75,
                "shadow_expected_r": 0.2,
                "shadow_recommended": True,
                "shadow_model_source": "model",
            },
            {
                "ticker": "BBB",
                "mode": "swing",
                "score": 90.0,
                "shadow_p_win": 0.8,
                "shadow_expected_r": 0.3,
                "shadow_recommended": True,
                "shadow_model_source": "model",
            },
        ]
    ).to_csv(shadow_path, index=False)

    _, selected, info = apply_model_v2_rollout_selection(
        filtered_combined=baseline,
        settings=settings,
        promotion_info={
            "rollout_pct": 10,
            "rollout_by_mode": {"t1": 10, "swing": 0},
            "live_active": True,
        },
        shadow_csv_path=str(shadow_path),
    )

    promoted = selected[selected.get("model_v2_live_selected", False).fillna(False)]
    assert set(promoted["ticker"]) == {"AAA"}
    assert info["rollout_by_mode"] == {"t1": 10, "swing": 0}
