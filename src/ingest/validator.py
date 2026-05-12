from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

CANONICAL_COLS = [
    "date",
    "ticker",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "ingested_at",
]

INTRADAY_CANONICAL_COLS = [
    "timestamp",
    "ticker",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "timeframe",
    "source",
    "ingested_at",
]


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    rows: int
    tickers: int
    max_date: pd.Timestamp | None


def _canonicalize(df: pd.DataFrame, source: str) -> pd.DataFrame:
    dfx = df.copy()
    required = ["date", "ticker", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in dfx.columns]
    if missing:
        raise ValueError(f"Missing required price columns: {missing}")

    dfx = dfx[required].copy()
    dfx["date"] = pd.to_datetime(dfx["date"], errors="coerce")
    dfx["ticker"] = dfx["ticker"].astype(str).str.upper().str.strip()

    for col in ["open", "high", "low", "close", "volume"]:
        dfx[col] = pd.to_numeric(dfx[col], errors="coerce")

    dfx["source"] = source
    dfx["ingested_at"] = datetime.utcnow()
    dfx = dfx[CANONICAL_COLS].sort_values(["ticker", "date"]).reset_index(drop=True)
    return dfx


def validate_prices(
    df: pd.DataFrame,
    source: str,
    max_staleness_days: int = 10,
    allow_empty: bool = False,
) -> tuple[pd.DataFrame, ValidationResult]:
    """Canonicalize and validate daily OHLCV data.

    Raises ValueError on invalid data. Returns canonicalized df and compact stats.
    """
    dfx = _canonicalize(df, source=source)

    if dfx.empty and not allow_empty:
        raise ValueError("Price dataset is empty")

    # Core null checks.
    null_mask = dfx[["date", "ticker", "close", "volume"]].isna().any(axis=1)
    if null_mask.any():
        raise ValueError(f"Found {int(null_mask.sum())} rows with null critical values")

    # Duplicates on ticker/date.
    dup = dfx.duplicated(subset=["ticker", "date"], keep=False)
    if dup.any():
        sample = dfx.loc[dup, ["ticker", "date"]].head(5).to_dict(orient="records")
        raise ValueError(f"Duplicate (ticker,date) rows detected. Sample: {sample}")

    # Non-negative checks.
    for col in ["open", "high", "low", "close", "volume"]:
        bad = dfx[col] < 0
        if bad.any():
            raise ValueError(f"Column {col} contains negative values")

    # OHLC consistency.
    high_ok = (dfx["high"] >= dfx[["open", "close", "low"]].max(axis=1))
    low_ok = (dfx["low"] <= dfx[["open", "close", "high"]].min(axis=1))
    if not bool(high_ok.all() and low_ok.all()):
        raise ValueError("OHLC consistency check failed")

    # Freshness check based on most recent date.
    max_date = dfx["date"].max()
    if pd.notna(max_date):
        today = pd.Timestamp.now(tz="UTC").date()
        max_d = pd.Timestamp(max_date).date()
        age_days = (today - max_d).days
        if age_days > max_staleness_days:
            raise ValueError(f"Data is stale by {age_days} days (> {max_staleness_days})")

    result = ValidationResult(
        ok=True,
        rows=len(dfx),
        tickers=int(dfx["ticker"].nunique()) if not dfx.empty else 0,
        max_date=max_date if pd.notna(max_date) else None,
    )
    return dfx, result


def _canonicalize_intraday(df: pd.DataFrame, source: str, timeframe: str) -> pd.DataFrame:
    dfx = df.copy()
    if "timestamp" not in dfx.columns and "date" in dfx.columns:
        dfx = dfx.rename(columns={"date": "timestamp"})
    required = ["timestamp", "ticker", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in dfx.columns]
    if missing:
        raise ValueError(f"Missing required intraday columns: {missing}")

    dfx = dfx[required].copy()
    dfx["timestamp"] = pd.to_datetime(dfx["timestamp"], errors="coerce")
    dfx["ticker"] = dfx["ticker"].astype(str).str.upper().str.strip()
    for col in ["open", "high", "low", "close", "volume"]:
        dfx[col] = pd.to_numeric(dfx[col], errors="coerce")

    dfx["timeframe"] = str(timeframe).strip().lower()
    dfx["source"] = source
    dfx["ingested_at"] = datetime.utcnow()
    dfx = dfx[INTRADAY_CANONICAL_COLS].sort_values(["ticker", "timestamp"]).reset_index(drop=True)
    return dfx


def validate_intraday_prices(
    df: pd.DataFrame,
    source: str,
    timeframe: str,
    max_staleness_minutes: int = 30,
    allow_empty: bool = False,
) -> tuple[pd.DataFrame, ValidationResult]:
    dfx = _canonicalize_intraday(df=df, source=source, timeframe=timeframe)

    if dfx.empty and not allow_empty:
        raise ValueError("Intraday dataset is empty")

    null_mask = dfx[["timestamp", "ticker", "close", "volume"]].isna().any(axis=1)
    if null_mask.any():
        raise ValueError(f"Found {int(null_mask.sum())} intraday rows with null critical values")

    dup = dfx.duplicated(subset=["ticker", "timestamp", "timeframe"], keep=False)
    if dup.any():
        sample = dfx.loc[dup, ["ticker", "timestamp", "timeframe"]].head(5).to_dict(orient="records")
        raise ValueError(f"Duplicate (ticker,timestamp,timeframe) rows detected. Sample: {sample}")

    for col in ["open", "high", "low", "close", "volume"]:
        bad = dfx[col] < 0
        if bad.any():
            raise ValueError(f"Intraday column {col} contains negative values")

    high_ok = (dfx["high"] >= dfx[["open", "close", "low"]].max(axis=1))
    low_ok = (dfx["low"] <= dfx[["open", "close", "high"]].min(axis=1))
    if not bool(high_ok.all() and low_ok.all()):
        raise ValueError("Intraday OHLC consistency check failed")

    max_ts = dfx["timestamp"].max()
    if pd.notna(max_ts):
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        max_dt = pd.Timestamp(max_ts)
        if getattr(max_dt, "tzinfo", None) is not None:
            max_dt = max_dt.tz_convert(None)
        age_minutes = int((now - max_dt).total_seconds() // 60)
        if age_minutes > max_staleness_minutes:
            raise ValueError(f"Intraday data is stale by {age_minutes} minutes (> {max_staleness_minutes})")

    result = ValidationResult(
        ok=True,
        rows=len(dfx),
        tickers=int(dfx["ticker"].nunique()) if not dfx.empty else 0,
        max_date=pd.Timestamp(max_ts) if pd.notna(max_ts) else None,
    )
    return dfx, result
