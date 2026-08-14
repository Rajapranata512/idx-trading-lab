from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.ingest.providers.base import PriceProvider


def _drop_incomplete_daily_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        frame.attrs["provider_quality"] = {
            "input_rows": 0,
            "valid_rows": 0,
            "dropped_incomplete_rows": 0,
            "dropped_ticker_count": 0,
            "dropped_tickers_sample": [],
            "dropped_date_count": 0,
            "dropped_dates_sample": [],
        }
        return frame

    cleaned = frame.copy()
    numeric_columns = ["open", "high", "low", "close", "volume"]
    for column in numeric_columns:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    finite_values = pd.Series(
        np.isfinite(cleaned[numeric_columns].to_numpy(dtype=float)).all(axis=1),
        index=cleaned.index,
    )
    valid_dates = pd.to_datetime(cleaned["date"], errors="coerce").notna()
    valid_tickers = cleaned["ticker"].astype(str).str.strip().ne("")
    invalid = ~(finite_values & valid_dates & valid_tickers)
    dropped = cleaned.loc[invalid].copy()
    cleaned = cleaned.loc[~invalid].copy().reset_index(drop=True)

    dropped_tickers = sorted(
        dropped["ticker"].dropna().astype(str).str.strip().unique().tolist()
    )
    dropped_dates = sorted(
        pd.to_datetime(dropped["date"], errors="coerce")
        .dropna()
        .dt.date.astype(str)
        .unique()
        .tolist()
    )
    cleaned.attrs["provider_quality"] = {
        "input_rows": int(len(frame)),
        "valid_rows": int(len(cleaned)),
        "dropped_incomplete_rows": int(invalid.sum()),
        "dropped_ticker_count": len(dropped_tickers),
        "dropped_tickers_sample": dropped_tickers[:10],
        "dropped_date_count": len(dropped_dates),
        "dropped_dates_sample": dropped_dates[:10],
    }
    return cleaned


class YFinanceProvider(PriceProvider):
    """Yahoo Finance provider used as practical fallback for EOD backfill."""

    def __init__(self, ticker_suffix: str = ".JK") -> None:
        self.ticker_suffix = ticker_suffix

    def fetch_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        tickers: list[str] | None = None,
    ) -> pd.DataFrame:
        try:
            import yfinance as yf
        except Exception as exc:
            raise RuntimeError("yfinance is not installed") from exc

        if not tickers:
            raise ValueError("Ticker list is required for yfinance provider")

        rows: list[dict] = []
        start = pd.Timestamp(start_date).date() if start_date else None
        end_inclusive = pd.Timestamp(end_date).date() if end_date else datetime.utcnow().date()
        end_exclusive = end_inclusive + timedelta(days=1)

        for ticker in sorted({t.upper().strip() for t in tickers}):
            symbol = f"{ticker}{self.ticker_suffix}"
            hist = yf.Ticker(symbol).history(
                start=start.isoformat() if start else None,
                end=end_exclusive.isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
            )
            if hist is None or hist.empty:
                continue
            frame = hist.reset_index().copy()
            date_col = "Date" if "Date" in frame.columns else frame.columns[0]
            for _, r in frame.iterrows():
                rows.append(
                    {
                        "date": pd.Timestamp(r[date_col]).date().isoformat(),
                        "ticker": ticker,
                        "open": r.get("Open"),
                        "high": r.get("High"),
                        "low": r.get("Low"),
                        "close": r.get("Close"),
                        "volume": r.get("Volume"),
                    }
                )

        return _drop_incomplete_daily_rows(pd.DataFrame(rows))

    def fetch_intraday(
        self,
        timeframe: str,
        start_datetime: str | None = None,
        end_datetime: str | None = None,
        tickers: list[str] | None = None,
        max_rows_per_ticker: int = 500,
    ) -> pd.DataFrame:
        try:
            import yfinance as yf
        except Exception as exc:
            raise RuntimeError("yfinance is not installed") from exc

        if not tickers:
            raise ValueError("Ticker list is required for yfinance provider")

        rows: list[dict] = []
        start = pd.Timestamp(start_datetime) if start_datetime else None
        if end_datetime:
            end_exclusive = pd.Timestamp(end_datetime) + pd.Timedelta(minutes=1)
        else:
            end_exclusive = pd.Timestamp.now(tz="UTC").tz_localize(None)
        interval = str(timeframe).strip().lower()
        allowed = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}
        if interval not in allowed:
            interval = "5m"

        for ticker in sorted({t.upper().strip() for t in tickers}):
            symbol = f"{ticker}{self.ticker_suffix}"
            hist = yf.Ticker(symbol).history(
                start=start.isoformat() if start is not None else None,
                end=end_exclusive.isoformat(),
                interval=interval,
                auto_adjust=False,
                actions=False,
            )
            if hist is None or hist.empty:
                continue

            frame = hist.reset_index().copy()
            ts_col = "Datetime" if "Datetime" in frame.columns else frame.columns[0]
            if max_rows_per_ticker > 0:
                frame = frame.tail(max_rows_per_ticker).copy()
            for _, r in frame.iterrows():
                rows.append(
                    {
                        "timestamp": pd.Timestamp(r[ts_col]).isoformat(),
                        "ticker": ticker,
                        "open": float(r.get("Open", 0.0)),
                        "high": float(r.get("High", 0.0)),
                        "low": float(r.get("Low", 0.0)),
                        "close": float(r.get("Close", 0.0)),
                        "volume": float(r.get("Volume", 0.0)),
                        "timeframe": interval,
                    }
                )

        return pd.DataFrame(rows)
