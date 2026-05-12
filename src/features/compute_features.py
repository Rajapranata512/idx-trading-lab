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


def _obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume per ticker group."""
    sign = np.sign(df["close"].diff())
    sign.iloc[0] = 0
    return (sign * df["volume"]).cumsum()


def _mfi(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Money Flow Index (volume-weighted RSI)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    mf = tp * df["volume"]
    delta = tp.diff()
    pos_mf = mf.where(delta > 0, 0.0).rolling(window).sum()
    neg_mf = mf.where(delta < 0, 0.0).rolling(window).sum()
    ratio = pos_mf / (neg_mf + 1e-9)
    return 100.0 - (100.0 / (1.0 + ratio))


def compute_features(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute EOD technical features per ticker (V2 expanded).

    Input columns: date,ticker,open,high,low,close,volume
    Output includes original features plus V2 additions:
      - returns (1d, 5d, 20d)
      - moving averages (20, 50, 200) + slopes + distance
      - RSI(14) + RSI slope
      - ATR(14)
      - rolling volatility (20d) + vol ratio
      - avg volume (20d) + volume ratio
      - cross-sectional ranks (ret_20d, vol_20d, score)
      - price bar position, high-low range
      - OBV slope, MFI(14)
      - momentum ratios
    """
    df = prices.copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    g = df.groupby("ticker", group_keys=False)

    # --- Original features ---
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
        df["rsi_14"] = g["close"].transform(lambda s: ta.momentum.rsi(s, window=14))
        _atr_parts = []
        for _ticker, _sub in df.groupby("ticker", group_keys=False):
            _atr_series = ta.volatility.average_true_range(
                high=_sub["high"], low=_sub["low"], close=_sub["close"], window=14
            )
            _atr_parts.append(_atr_series)
        df["atr_14"] = pd.concat(_atr_parts)
    else:
        df["rsi_14"] = g["close"].transform(lambda s: _rsi(s, window=14))
        _atr_parts = []
        for _ticker, _sub in df.groupby("ticker", group_keys=False):
            _atr_parts.append(_atr(_sub, window=14))
        df["atr_14"] = pd.concat(_atr_parts)

    df["atr_pct"] = (df["atr_14"] / (df["close"] + 1e-9)) * 100.0

    # --- V2 features: MA slopes (trend acceleration) ---
    df["ma_slope_20"] = g["ma_20"].transform(
        lambda s: (s - s.shift(5)) / (5.0)
    ) / (df["close"] + 1e-9)
    df["ma_slope_50"] = g["ma_50"].transform(
        lambda s: (s - s.shift(10)) / (10.0)
    ) / (df["close"] + 1e-9)

    # --- V2 features: Distance to MA (mean-reversion signals) ---
    df["dist_ma_20"] = (df["close"] - df["ma_20"]) / (df["close"] + 1e-9)
    df["dist_ma_50"] = (df["close"] - df["ma_50"]) / (df["close"] + 1e-9)

    # --- V2 features: Volatility regime ---
    df["vol_60d"] = g["ret_1d"].transform(lambda s: s.rolling(60).std())
    df["vol_ratio"] = df["vol_20d"] / (df["vol_60d"] + 1e-9)

    # --- V2 features: Momentum ratio ---
    df["ret_5d_20d_ratio"] = df["ret_5d"] / (df["ret_20d"].abs() + 1e-9)

    # --- V2 features: Price bar structure ---
    df["high_low_range"] = (df["high"] - df["low"]) / (df["close"] + 1e-9)
    df["close_position"] = (df["close"] - df["low"]) / (
        df["high"] - df["low"] + 1e-9
    )

    # --- V2 features: Volume spike ---
    df["volume_ratio_20d"] = df["volume"] / (df["avg_vol_20d"] + 1e-9)
    df["turnover_ratio_20d"] = df["turnover"] / (df["turnover_20d"] + 1e-9)

    # --- V2 features: RSI momentum ---
    df["rsi_slope"] = g["rsi_14"].transform(lambda s: s - s.shift(5))

    # --- V2 features: OBV slope (linear trend of OBV over 20 bars) ---
    def _obv_slope_20(sub: pd.DataFrame) -> pd.Series:
        obv = _obv(sub)
        x = np.arange(20, dtype=float)
        x_demean = x - x.mean()
        denom = (x_demean ** 2).sum()

        def _slope(window):
            if len(window) < 20 or np.isnan(window).any():
                return np.nan
            y = np.array(window, dtype=float)
            y_demean = y - y.mean()
            return float(np.dot(x_demean, y_demean) / (denom + 1e-9))

        return obv.rolling(20).apply(_slope, raw=True)

    _obv_parts = []
    for _ticker, _sub in df.groupby("ticker", group_keys=False):
        _obv_parts.append(_obv_slope_20(_sub))
    df["obv_slope"] = pd.concat(_obv_parts)
    # Normalize OBV slope by average volume so it's comparable across tickers
    df["obv_slope"] = df["obv_slope"] / (df["avg_vol_20d"] + 1e-9)

    # --- V2 features: Money Flow Index ---
    _mfi_parts = []
    for _ticker, _sub in df.groupby("ticker", group_keys=False):
        _mfi_parts.append(_mfi(_sub))
    df["mfi_14"] = pd.concat(_mfi_parts)

    # --- V2 features: breakout structure and MA stack ---
    df["high_20"] = g["high"].transform(lambda s: s.rolling(20).max())
    df["low_20"] = g["low"].transform(lambda s: s.rolling(20).min())
    df["dist_high_20"] = (df["close"] / (df["high_20"] + 1e-9)) - 1.0
    df["dist_low_20"] = (df["close"] / (df["low_20"] + 1e-9)) - 1.0
    df["ma_gap_20_50"] = (df["ma_20"] - df["ma_50"]) / (df["close"] + 1e-9)
    df["ma_stack_bullish"] = (
        (df["ma_20"] > df["ma_50"]) & (df["ma_50"] > df["ma_200"])
    ).astype(float)

    # --- V2 features: Cross-sectional ranks (percentile within universe per date) ---
    if "date" in df.columns:
        date_g = df.groupby("date")
        df["rank_ret_20d"] = date_g["ret_20d"].rank(pct=True, na_option="keep")
        df["rank_vol_20d"] = date_g["vol_20d"].rank(pct=True, na_option="keep")
        if "score" in df.columns:
            df["rank_score"] = date_g["score"].rank(pct=True, na_option="keep")

        market_ma20 = (df["close"] > df["ma_20"]).astype(float)
        market_ma50 = (df["close"] > df["ma_50"]).astype(float)
        df["market_breadth_ma20_pct"] = market_ma20.groupby(df["date"]).transform("mean") * 100.0
        df["market_breadth_ma50_pct"] = market_ma50.groupby(df["date"]).transform("mean") * 100.0
        df["market_avg_ret20_pct"] = date_g["ret_20d"].transform("mean") * 100.0
        df["market_median_atr_pct"] = date_g["atr_pct"].transform("median")
        df["relative_ret_20d"] = df["ret_20d"] - (df["market_avg_ret20_pct"] / 100.0)

    return df
