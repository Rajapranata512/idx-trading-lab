from __future__ import annotations

import pandas as pd

from src.features.compute_features import compute_features
from src.strategy import rank_all_modes


def test_rank_all_modes_returns_two_tables(sample_prices_df: pd.DataFrame):
    feats = compute_features(sample_prices_df)
    top_t1, top_swing, combined = rank_all_modes(feats, min_avg_volume_20d=100000, top_n_per_mode=2)
    assert len(top_t1) <= 2
    assert len(top_swing) <= 2
    assert set(combined["mode"].unique()) <= {"t1", "swing"}


def test_scores_are_bounded_0_100(sample_prices_df: pd.DataFrame):
    feats = compute_features(sample_prices_df)
    top_t1, top_swing, _ = rank_all_modes(feats, min_avg_volume_20d=100000, top_n_per_mode=5)
    assert top_t1["score"].between(0, 100).all()
    assert top_swing["score"].between(0, 100).all()


def test_ranking_is_monotonic_desc(sample_prices_df: pd.DataFrame):
    feats = compute_features(sample_prices_df)
    top_t1, _, _ = rank_all_modes(feats, min_avg_volume_20d=100000, top_n_per_mode=5)
    scores = top_t1["score"].tolist()
    assert scores == sorted(scores, reverse=True)
