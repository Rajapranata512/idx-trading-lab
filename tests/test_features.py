from __future__ import annotations

import pandas as pd

from src.features.compute_features import compute_features


def test_compute_features_adds_required_columns(sample_prices_df: pd.DataFrame):
    feats = compute_features(sample_prices_df)
    expected = {
        "ret_1d",
        "ret_5d",
        "ret_20d",
        "ma_20",
        "ma_50",
        "ma_200",
        "vol_20d",
        "avg_vol_20d",
        "rsi_14",
        "atr_14",
        "turnover_20d",
        "atr_pct",
    }
    assert expected.issubset(set(feats.columns))


def test_compute_features_has_initial_nans_for_rolling(sample_prices_df: pd.DataFrame):
    feats = compute_features(sample_prices_df)
    one_ticker = feats[feats["ticker"] == "BBCA"].reset_index(drop=True)
    assert one_ticker.loc[:18, "ma_20"].isna().all()
    assert one_ticker.loc[19:, "ma_20"].notna().any()


def test_compute_features_rsi_atr_not_all_nan(sample_prices_df: pd.DataFrame):
    feats = compute_features(sample_prices_df)
    last = feats.groupby("ticker").tail(1)
    assert last["rsi_14"].notna().any()
    assert last["atr_14"].notna().any()
