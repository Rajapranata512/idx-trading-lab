from __future__ import annotations

import pandas as pd

from src.strategy.swing_model import build_swing_score_frame, score_swing_candidates
from src.strategy.t1_model import score_t1_candidates


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
    t1 = df.copy()
    t1_trend = (t1["close"] > t1["ma_20"]).astype(float)
    t1_momentum = (t1["ret_5d"].fillna(0) > 0).astype(float)
    v = t1["vol_20d"]
    v_lo, v_hi = v.quantile(0.1), v.quantile(0.9)
    t1_vol_ok = ((v >= v_lo) & (v <= v_hi)).astype(float).fillna(0.0)
    t1_ret = t1["ret_5d"].clip(lower=t1["ret_5d"].quantile(0.05), upper=t1["ret_5d"].quantile(0.95))
    t1_mom_strength = (t1_ret - t1_ret.min()) / (t1_ret.max() - t1_ret.min() + 1e-9)
    t1["score"] = (35 * t1_trend) + (30 * t1_momentum) + (20 * t1_mom_strength.fillna(0.0)) + (15 * t1_vol_ok)
    t1["score"] = t1["score"].clip(0, 100)
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
