from __future__ import annotations

import pandas as pd

from src.strategy.swing_model import build_swing_score_frame, score_swing_candidates
from src.strategy.t1_model import build_t1_score_frame, score_t1_candidates


def rank_all_modes(
    features: pd.DataFrame,
    min_avg_volume_20d: float,
    top_n_per_mode: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    top_t1 = score_t1_candidates(
        features=features,
        min_avg_volume_20d=min_avg_volume_20d,
        top_n=top_n_per_mode,
    )
    top_swing = score_swing_candidates(
        features=features,
        min_avg_volume_20d=min_avg_volume_20d,
        top_n=top_n_per_mode,
    )
    combined = pd.concat([top_t1, top_swing], ignore_index=True, sort=False)
    return top_t1, top_swing, combined


def score_history_modes(features: pd.DataFrame, min_avg_volume_20d: float) -> pd.DataFrame:
    """Create historical score rows per date for backtesting.

    This keeps one row per ticker-date-mode and only valid liquidity rows.
    """
    df = features.copy()
    df = df[df["avg_vol_20d"].fillna(0) >= min_avg_volume_20d].copy()

    # T+1 historical score.
    t1 = build_t1_score_frame(df, group_by_date=True)
    t1["mode"] = "t1"

    # Swing historical score.
    sw = df[
        (df["close"] > df["ma_50"]) &
        (df["ret_20d"].fillna(0) > 0)
    ].copy()
    sw = build_swing_score_frame(sw)
    sw["mode"] = "swing"

    out = pd.concat([t1, sw], ignore_index=True, sort=False)
    return out.sort_values(["date", "mode", "score"], ascending=[True, True, False]).reset_index(drop=True)
