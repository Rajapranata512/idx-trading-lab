from __future__ import annotations

import pandas as pd


def score_intraday_candidates(
    features: pd.DataFrame,
    min_avg_volume_20bars: float,
    top_n: int = 15,
) -> pd.DataFrame:
    """Score intraday candidates from latest bar per ticker."""
    latest = features.sort_values(["ticker", "timestamp"]).groupby("ticker").tail(1).copy()
    latest = latest[latest["avg_vol_20d"].fillna(0) >= min_avg_volume_20bars].copy()
    if latest.empty:
        latest["score"] = pd.Series(dtype=float)
        latest["mode"] = "intraday"
        latest["reason"] = "MA20/MA50 trend + bar momentum + ATR activity"
        latest["rank"] = pd.Series(dtype=int)
        return latest

    trend_fast = (latest["close"] > latest["ma_20"]).astype(float)
    trend_mid = (latest["close"] > latest["ma_50"]).astype(float)
    mom_bar = (latest["ret_1d"].fillna(0) > 0).astype(float)

    ret_5 = latest["ret_5d"].clip(
        lower=latest["ret_5d"].quantile(0.05),
        upper=latest["ret_5d"].quantile(0.95),
    )
    mom_5 = ((ret_5 - ret_5.min()) / (ret_5.max() - ret_5.min() + 1e-9)).fillna(0.0)

    atr_pct = latest["atr_pct"].clip(
        lower=latest["atr_pct"].quantile(0.05),
        upper=latest["atr_pct"].quantile(0.95),
    )
    atr_activity = ((atr_pct - atr_pct.min()) / (atr_pct.max() - atr_pct.min() + 1e-9)).fillna(0.0)

    score = (25 * trend_fast) + (20 * trend_mid) + (20 * mom_bar) + (20 * mom_5) + (15 * atr_activity)
    latest["score"] = score.clip(lower=0, upper=100).round(2)
    latest["mode"] = "intraday"
    latest["reason"] = "MA20/MA50 trend + bar momentum + ATR activity"
    latest = latest.sort_values("score", ascending=False).head(max(1, int(top_n))).copy()
    latest["rank"] = range(1, len(latest) + 1)
    return latest

