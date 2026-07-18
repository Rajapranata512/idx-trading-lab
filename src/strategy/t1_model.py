from __future__ import annotations

import pandas as pd


def build_t1_score_frame(
    features: pd.DataFrame,
    group_by_date: bool = False,
) -> pd.DataFrame:
    """Score a T1 cross-section without using observations from future dates."""
    scored = features.copy()
    if scored.empty:
        scored["score"] = pd.Series(dtype=float)
        return scored

    trend = (scored["close"] > scored["ma_20"]).astype(float)
    momentum = (scored["ret_5d"].fillna(0) > 0).astype(float)
    volatility = pd.to_numeric(scored["vol_20d"], errors="coerce")
    returns = pd.to_numeric(scored["ret_5d"], errors="coerce")

    if group_by_date and "date" in scored.columns:
        dates = pd.to_datetime(scored["date"], errors="coerce")
        vol_low = volatility.groupby(dates).transform(lambda values: values.quantile(0.1))
        vol_high = volatility.groupby(dates).transform(lambda values: values.quantile(0.9))
        return_low = returns.groupby(dates).transform(lambda values: values.quantile(0.05))
        return_high = returns.groupby(dates).transform(lambda values: values.quantile(0.95))
        clipped_returns = returns.clip(lower=return_low, upper=return_high)
        return_min = clipped_returns.groupby(dates).transform("min")
        return_max = clipped_returns.groupby(dates).transform("max")
    else:
        vol_low = pd.Series(volatility.quantile(0.1), index=scored.index)
        vol_high = pd.Series(volatility.quantile(0.9), index=scored.index)
        clipped_returns = returns.clip(
            lower=returns.quantile(0.05),
            upper=returns.quantile(0.95),
        )
        return_min = pd.Series(clipped_returns.min(), index=scored.index)
        return_max = pd.Series(clipped_returns.max(), index=scored.index)

    vol_ok = ((volatility >= vol_low) & (volatility <= vol_high)).astype(float).fillna(0.0)
    momentum_strength = (
        (clipped_returns - return_min) / (return_max - return_min + 1e-9)
    ).fillna(0.0)
    scored["score"] = (
        (35 * trend)
        + (30 * momentum)
        + (20 * momentum_strength)
        + (15 * vol_ok)
    ).clip(lower=0, upper=100).round(2)
    scored["reason"] = "Trend MA20 + momentum 5D + volatility sehat"
    return scored


def score_t1_candidates(
    features: pd.DataFrame,
    min_avg_volume_20d: float,
    top_n: int = 10,
) -> pd.DataFrame:
    """Score short-hold (T+1) candidates from the latest bar per ticker."""
    latest = features.sort_values(["ticker", "date"]).groupby("ticker").tail(1).copy()
    latest = latest[latest["avg_vol_20d"].fillna(0) >= min_avg_volume_20d].copy()

    latest = build_t1_score_frame(latest, group_by_date=False)
    latest["mode"] = "t1"
    latest = latest.sort_values("score", ascending=False).head(top_n).copy()
    latest["rank"] = range(1, len(latest) + 1)
    return latest
