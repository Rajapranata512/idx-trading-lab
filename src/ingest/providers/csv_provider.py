from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingest.providers.base import PriceProvider


class CSVProvider(PriceProvider):
    """Deterministic local CSV provider."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def fetch_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        tickers: list[str] | None = None,
    ) -> pd.DataFrame:
        if not self.path.exists():
            raise FileNotFoundError(f"CSV file not found: {self.path}")

        df = pd.read_csv(self.path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")

        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]
        if tickers:
            ticker_set = {t.upper().strip() for t in tickers}
            df = df[df["ticker"].astype(str).str.upper().isin(ticker_set)]
        return df.reset_index(drop=True)
