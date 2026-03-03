from __future__ import annotations

import pandas as pd


def score_t1_candidates(
    features: pd.DataFrame,
    min_avg_volume_20d: float,
    top_n: int = 10,
) -> pd.DataFrame:
    """Score short-hold (T+1) candidates from the latest bar per ticker."""
    latest = features.sort_values(["ticker", "date"]).groupby("ticker").tail(1).copy()
    latest = latest[latest["avg_vol_20d"].fillna(0) >= min_avg_volume_20d].copy()

    trend = (latest["close"] > latest["ma_20"]).astype(float)
    momentum = (latest["ret_5d"].fillna(0) > 0).astype(float)

    v = latest["vol_20d"]
    v_lo, v_hi = v.quantile(0.1), v.quantile(0.9)
    vol_ok = ((v >= v_lo) & (v <= v_hi)).astype(float).fillna(0.0)

    ret_5d = latest["ret_5d"].clip(
        lower=latest["ret_5d"].quantile(0.05),
        upper=latest["ret_5d"].quantile(0.95),
    )
    mom_strength = (ret_5d - ret_5d.min()) / (ret_5d.max() - ret_5d.min() + 1e-9)
    mom_strength = mom_strength.fillna(0.0)

    score = (35 * trend) + (30 * momentum) + (20 * mom_strength) + (15 * vol_ok)
    latest["score"] = score.clip(lower=0, upper=100).round(2)
    latest["mode"] = "t1"
    latest["reason"] = "Trend MA20 + momentum 5D + volatility sehat"
    latest = latest.sort_values("score", ascending=False).head(top_n).copy()
    latest["rank"] = range(1, len(latest) + 1)
    return latest
