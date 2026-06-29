from __future__ import annotations

import pandas as pd


def compute_trailing_stop(
    entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    high_since_entry: float,
    atr: float = 0.0,
    trail_pct: float = 0.025,
    atr_trail_multiple: float = 1.5,
) -> float:
    """Compute adaptive trailing stop for a single position.

    Trailing logic:
    - Price below TP1: keep original stop (no trailing)
    - Price reached TP1: move stop to breakeven (entry price)
    - Price reached TP2: trail at max(TP1, high - 2.5%, high - 1.5*ATR)

    Parameters
    ----------
    entry : float
        Entry (buy) price.
    stop : float
        Original static stop-loss price.
    tp1 : float
        Take-profit level 1.
    tp2 : float
        Take-profit level 2.
    high_since_entry : float
        Highest price observed since position was opened.
    atr : float
        Average True Range for the ticker (optional, improves trail accuracy).
    trail_pct : float
        Percentage trail distance below the high (default 2.5%).
    atr_trail_multiple : float
        ATR multiplier for trailing distance (default 1.5x).

    Returns
    -------
    float
        The computed trailing stop price.
    """
    if high_since_entry <= 0 or entry <= 0:
        return stop

    # Phase 1: Price has not reached TP1 yet - keep original stop
    if high_since_entry < tp1:
        return stop

    # Phase 2: Price reached TP1 but not TP2 - move to breakeven
    if high_since_entry < tp2:
        return max(stop, entry)

    # Phase 3: Price reached or exceeded TP2 - active trailing
    trail_by_pct = high_since_entry * (1.0 - trail_pct)
    trail_by_atr = high_since_entry - (atr_trail_multiple * atr) if atr > 0 else 0.0

    # Take the highest (most protective) of the trail methods
    trail_candidates = [tp1, trail_by_pct]
    if trail_by_atr > 0:
        trail_candidates.append(trail_by_atr)

    trailing_stop = max(trail_candidates)

    # Never let trailing stop go below the original stop
    return max(stop, trailing_stop)


def compute_trailing_stops_df(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    trail_pct: float = 0.025,
    atr_trail_multiple: float = 1.5,
) -> pd.DataFrame:
    """Compute trailing stops for a DataFrame of open signals.

    Parameters
    ----------
    signals : pd.DataFrame
        Must contain columns: ticker, entry, stop, tp1, tp2, date (signal date).
    prices : pd.DataFrame
        Daily price data with columns: ticker, date, high, close.

    Returns
    -------
    pd.DataFrame
        The signals DataFrame with added columns:
        - high_since_entry: highest price since signal date
        - trailing_stop: computed adaptive trailing stop
        - trailing_status: one of 'original', 'breakeven', 'trailing'
    """
    if signals.empty:
        signals = signals.copy()
        signals["high_since_entry"] = []
        signals["trailing_stop"] = []
        signals["trailing_status"] = []
        return signals

    result = signals.copy()
    highs = []
    trailing_stops = []
    statuses = []

    for _, row in result.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        signal_date = pd.to_datetime(row.get("date"), errors="coerce")
        entry_price = float(row.get("entry", 0) or 0)
        stop_price = float(row.get("stop", 0) or 0)
        tp1_price = float(row.get("tp1", 0) or 0)
        tp2_price = float(row.get("tp2", 0) or 0)

        # Find highest price since signal was generated
        if not prices.empty and pd.notna(signal_date) and ticker:
            ticker_prices = prices[
                (prices["ticker"].str.upper() == ticker)
                & (pd.to_datetime(prices["date"], errors="coerce") >= signal_date)
            ]
            if not ticker_prices.empty and "high" in ticker_prices.columns:
                high_since = float(
                    pd.to_numeric(ticker_prices["high"], errors="coerce").max()
                )
            else:
                high_since = entry_price
        else:
            high_since = entry_price

        # Get ATR if available
        atr_val = float(row.get("atr_14", 0) or row.get("atr", 0) or 0)

        ts = compute_trailing_stop(
            entry=entry_price,
            stop=stop_price,
            tp1=tp1_price,
            tp2=tp2_price,
            high_since_entry=high_since,
            atr=atr_val,
            trail_pct=trail_pct,
            atr_trail_multiple=atr_trail_multiple,
        )

        # Determine status
        if ts > entry_price:
            status = "trailing"
        elif abs(ts - entry_price) < 0.01:
            status = "breakeven"
        else:
            status = "original"

        highs.append(round(high_since, 2))
        trailing_stops.append(round(ts, 2))
        statuses.append(status)

    result["high_since_entry"] = highs
    result["trailing_stop"] = trailing_stops
    result["trailing_status"] = statuses
    return result
