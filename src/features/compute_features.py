from __future__ import annotations

import pandas as pd
import numpy as np

try:
    import ta  # type: ignore
except Exception:
    ta = None


def _rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr_components = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    true_range = tr_components.max(axis=1)
    return true_range.rolling(window).mean()


def compute_features(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute common EOD technical features per ticker.

    Input columns: date,ticker,open,high,low,close,volume
    Output includes:
      - returns (1d, 5d, 20d)
      - moving averages (20, 50, 200)
      - RSI(14) if 'ta' is available
      - ATR(14) if 'ta' is available
      - rolling volatility (20d)
      - avg volume (20d)
    """
    df = prices.copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    g = df.groupby("ticker", group_keys=False)

    df["ret_1d"] = g["close"].pct_change(1)
    df["ret_5d"] = g["close"].pct_change(5)
    df["ret_20d"] = g["close"].pct_change(20)

    for w in [20, 50, 200]:
        df[f"ma_{w}"] = g["close"].transform(lambda s: s.rolling(w).mean())

    df["vol_20d"] = g["ret_1d"].transform(lambda s: s.rolling(20).std())

    df["avg_vol_20d"] = g["volume"].transform(lambda s: s.rolling(20).mean())
    df["turnover"] = df["close"] * df["volume"]
    df["turnover_20d"] = g["turnover"].transform(lambda s: s.rolling(20).mean())

    if ta is not None:
        # RSI and ATR using ta library
        df["rsi_14"] = g["close"].transform(lambda s: ta.momentum.rsi(s, window=14))
        df["atr_14"] = g[["high", "low", "close"]].apply(
            lambda x: ta.volatility.average_true_range(
                high=x["high"], low=x["low"], close=x["close"], window=14
            )
        ).reset_index(level=0, drop=True)
    else:
        df["rsi_14"] = g["close"].transform(lambda s: _rsi(s, window=14))
        df["atr_14"] = g[["high", "low", "close"]].apply(
            lambda x: _atr(x, window=14)
        ).reset_index(level=0, drop=True)

    df["atr_pct"] = (df["atr_14"] / (df["close"] + 1e-9)) * 100.0

    return df
