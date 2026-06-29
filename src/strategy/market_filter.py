from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MarketFilterResult:
    """Result of market-wide defensive filter evaluation."""
    is_defensive: bool
    breadth_ma20_pct: float
    breadth_ma50_pct: float
    market_avg_ret20_pct: float
    position_size_multiplier: float  # 1.0 = normal, 0.5 = half size
    min_score_boost: float  # additional points added to min score threshold
    reason: str


def evaluate_market_filter(
    features: pd.DataFrame,
    defensive_breadth_ma50_threshold: float = 40.0,
    defensive_breadth_ma20_threshold: float = 45.0,
    severe_breadth_ma50_threshold: float = 25.0,
    defensive_position_mult: float = 0.5,
    severe_position_mult: float = 0.25,
    defensive_score_boost: float = 5.0,
    severe_score_boost: float = 10.0,
) -> MarketFilterResult:
    """Evaluate market-wide conditions and return defensive filter result.

    This acts as a 'circuit breaker' for the trading system. When the
    broad market is bearish (most stocks below their moving averages),
    this filter:
    - Reduces position sizes (less capital at risk)
    - Raises minimum score thresholds (only take the strongest signals)

    Parameters
    ----------
    features : pd.DataFrame
        Feature DataFrame containing market_breadth_ma20_pct and
        market_breadth_ma50_pct columns.
    defensive_breadth_ma50_threshold : float
        If breadth_ma50 falls below this, enter defensive mode.
    defensive_breadth_ma20_threshold : float
        If breadth_ma20 falls below this, enter defensive mode.
    severe_breadth_ma50_threshold : float
        If breadth_ma50 falls below this, enter severe defensive mode.
    defensive_position_mult : float
        Position size multiplier in defensive mode (default 0.5 = half size).
    severe_position_mult : float
        Position size multiplier in severe defensive mode (default 0.25).
    defensive_score_boost : float
        Extra points added to minimum score threshold in defensive mode.
    severe_score_boost : float
        Extra points added to minimum score threshold in severe mode.

    Returns
    -------
    MarketFilterResult
        Contains the defensive state, multipliers, and reasoning.
    """
    if features.empty:
        return MarketFilterResult(
            is_defensive=False,
            breadth_ma20_pct=50.0,
            breadth_ma50_pct=50.0,
            market_avg_ret20_pct=0.0,
            position_size_multiplier=1.0,
            min_score_boost=0.0,
            reason="No data available, using default (non-defensive)",
        )

    # Get latest market breadth values (they are per-date, same across tickers)
    latest = features.sort_values("date").drop_duplicates("date", keep="last").tail(1)

    breadth_ma20 = 50.0
    breadth_ma50 = 50.0
    avg_ret20 = 0.0

    if "market_breadth_ma20_pct" in latest.columns:
        val = pd.to_numeric(latest["market_breadth_ma20_pct"], errors="coerce").iloc[-1]
        if pd.notna(val):
            breadth_ma20 = float(val)

    if "market_breadth_ma50_pct" in latest.columns:
        val = pd.to_numeric(latest["market_breadth_ma50_pct"], errors="coerce").iloc[-1]
        if pd.notna(val):
            breadth_ma50 = float(val)

    if "market_avg_ret20_pct" in latest.columns:
        val = pd.to_numeric(latest["market_avg_ret20_pct"], errors="coerce").iloc[-1]
        if pd.notna(val):
            avg_ret20 = float(val)

    # Severe defensive: market is crashing
    if breadth_ma50 < severe_breadth_ma50_threshold:
        return MarketFilterResult(
            is_defensive=True,
            breadth_ma20_pct=breadth_ma20,
            breadth_ma50_pct=breadth_ma50,
            market_avg_ret20_pct=avg_ret20,
            position_size_multiplier=severe_position_mult,
            min_score_boost=severe_score_boost,
            reason=(
                f"SEVERE DEFENSIVE: Only {breadth_ma50:.1f}% of stocks above MA50 "
                f"(threshold: {severe_breadth_ma50_threshold}%). "
                f"Position size cut to {severe_position_mult*100:.0f}%, "
                f"min score raised by +{severe_score_boost:.0f} pts."
            ),
        )

    # Normal defensive: market is weak
    if (
        breadth_ma50 < defensive_breadth_ma50_threshold
        or breadth_ma20 < defensive_breadth_ma20_threshold
    ):
        reasons = []
        if breadth_ma50 < defensive_breadth_ma50_threshold:
            reasons.append(
                f"breadth_MA50={breadth_ma50:.1f}% < {defensive_breadth_ma50_threshold}%"
            )
        if breadth_ma20 < defensive_breadth_ma20_threshold:
            reasons.append(
                f"breadth_MA20={breadth_ma20:.1f}% < {defensive_breadth_ma20_threshold}%"
            )

        return MarketFilterResult(
            is_defensive=True,
            breadth_ma20_pct=breadth_ma20,
            breadth_ma50_pct=breadth_ma50,
            market_avg_ret20_pct=avg_ret20,
            position_size_multiplier=defensive_position_mult,
            min_score_boost=defensive_score_boost,
            reason=(
                f"DEFENSIVE MODE: {'; '.join(reasons)}. "
                f"Position size cut to {defensive_position_mult*100:.0f}%, "
                f"min score raised by +{defensive_score_boost:.0f} pts."
            ),
        )

    # Normal / risk-on conditions
    return MarketFilterResult(
        is_defensive=False,
        breadth_ma20_pct=breadth_ma20,
        breadth_ma50_pct=breadth_ma50,
        market_avg_ret20_pct=avg_ret20,
        position_size_multiplier=1.0,
        min_score_boost=0.0,
        reason=(
            f"NORMAL: breadth_MA50={breadth_ma50:.1f}%, "
            f"breadth_MA20={breadth_ma20:.1f}% — market conditions healthy."
        ),
    )
