from __future__ import annotations

import pandas as pd


def score_swing_candidates(
    features: pd.DataFrame,
    min_avg_volume_20d: float,
    top_n: int = 10,
) -> pd.DataFrame:
    """Score swing (1-4w) candidates from latest bar per ticker."""
    latest = features.sort_values(["ticker", "date"]).groupby("ticker").tail(1).copy()
    latest = latest[latest["avg_vol_20d"].fillna(0) >= min_avg_volume_20d].copy()

    # Hard filter: medium trend up + positive 20D momentum.
    latest = latest[
        (latest["close"] > latest["ma_50"]) &
        (latest["ret_20d"].fillna(0) > 0)
    ].copy()
    if latest.empty:
        latest["score"] = pd.Series(dtype=float)
        latest["mode"] = "swing"
        latest["reason"] = "Trend MA50 + momentum 20D + ATR expansion"
        latest["rank"] = pd.Series(dtype=int)
        return latest

    r20 = latest["ret_20d"].clip(
        lower=latest["ret_20d"].quantile(0.05),
        upper=latest["ret_20d"].quantile(0.95),
    )
    mom20 = ((r20 - r20.min()) / (r20.max() - r20.min() + 1e-9)).fillna(0.0)

    atr_pct = latest["atr_pct"].clip(
        lower=latest["atr_pct"].quantile(0.05),
        upper=latest["atr_pct"].quantile(0.95),
    )
    atr_expansion = ((atr_pct - atr_pct.min()) / (atr_pct.max() - atr_pct.min() + 1e-9)).fillna(0.0)

    score = (60 * mom20) + (40 * atr_expansion)
    latest["score"] = score.clip(lower=0, upper=100).round(2)
    latest["mode"] = "swing"
    latest["reason"] = "Trend MA50 + momentum 20D + ATR expansion"
    latest = latest.sort_values("score", ascending=False).head(top_n).copy()
    latest["rank"] = range(1, len(latest) + 1)
    return latest
