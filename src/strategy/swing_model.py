from __future__ import annotations

import pandas as pd


def _normalized(series: pd.Series, lower_q: float = 0.05, upper_q: float = 0.95, neutral: float = 0.5) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce")
    if clean.notna().sum() <= 1:
        return pd.Series([neutral] * len(clean), index=clean.index, dtype=float)
    lo = clean.quantile(lower_q)
    hi = clean.quantile(upper_q)
    clipped = clean.clip(lower=lo, upper=hi)
    span = float(clipped.max() - clipped.min())
    if span <= 1e-9:
        return pd.Series([neutral] * len(clean), index=clean.index, dtype=float)
    return ((clipped - clipped.min()) / (span + 1e-9)).fillna(neutral)


def _safe_col(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    """Return column as a numeric Series, falling back to a constant Series."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype=float)


def build_swing_score_frame(features: pd.DataFrame) -> pd.DataFrame:
    latest = features.copy()
    if latest.empty:
        latest["score"] = pd.Series(dtype=float)
        latest["reason"] = "Trend stack + relative momentum + breakout proximity + volume confirmation"
        return latest

    mom20 = _normalized(latest.get("ret_20d", pd.Series(dtype=float, index=latest.index)))
    rel20 = _normalized(latest.get("relative_ret_20d", latest.get("ret_20d", pd.Series(dtype=float, index=latest.index))))
    trend_stack = (
        (pd.to_numeric(latest.get("close"), errors="coerce") > pd.to_numeric(latest.get("ma_20"), errors="coerce")).astype(float)
        + (pd.to_numeric(latest.get("ma_20"), errors="coerce") > pd.to_numeric(latest.get("ma_50"), errors="coerce")).astype(float)
        + _safe_col(latest, "ma_stack_bullish", 0.0)
    ) / 3.0
    breakout_source = _safe_col(latest, "dist_high_20", -0.15)
    breakout = ((breakout_source.clip(lower=-0.15, upper=0.05) + 0.15) / 0.20).clip(lower=0.0, upper=1.0)
    volume_confirm = _normalized(_safe_col(latest, "turnover_ratio_20d", _safe_col(latest, "volume_ratio_20d", 1.0)))
    vol_quality = (1.0 - _normalized(_safe_col(latest, "atr_pct", _safe_col(latest, "vol_ratio", 0.0)))).clip(lower=0.0, upper=1.0)

    breadth20 = (_safe_col(latest, "market_breadth_ma20_pct", 50.0) / 100.0).clip(0.0, 1.0)
    breadth50 = (_safe_col(latest, "market_breadth_ma50_pct", 50.0) / 100.0).clip(0.0, 1.0)
    market_ret = _safe_col(latest, "market_avg_ret20_pct", 0.0)
    market_ret_support = ((market_ret.clip(lower=-15.0, upper=15.0) + 15.0) / 30.0).clip(0.0, 1.0)
    market_atr = _safe_col(latest, "market_median_atr_pct", 4.0)
    market_atr_support = (1.0 - (market_atr.clip(lower=0.0, upper=12.0) / 12.0)).clip(0.0, 1.0)
    market_support = ((breadth20 + breadth50 + market_ret_support + market_atr_support) / 4.0).clip(0.0, 1.0)

    score = (
        (22.0 * mom20)
        + (18.0 * rel20)
        + (16.0 * trend_stack.clip(lower=0.0, upper=1.0))
        + (14.0 * breakout)
        + (12.0 * volume_confirm)
        + (10.0 * vol_quality)
        + (8.0 * market_support)
    )

    latest["score"] = score.clip(lower=0.0, upper=100.0).round(2)
    latest["reason"] = "Trend stack + relative momentum + breakout proximity + volume confirmation + volatility discipline"
    return latest


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
        latest["reason"] = "Trend stack + relative momentum + breakout proximity + volume confirmation"
        latest["rank"] = pd.Series(dtype=int)
        return latest

    latest = build_swing_score_frame(latest)
    latest["mode"] = "swing"
    latest = latest.sort_values("score", ascending=False).head(top_n).copy()
    latest["rank"] = range(1, len(latest) + 1)
    return latest
