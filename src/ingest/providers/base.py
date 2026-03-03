from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class PriceProvider(ABC):
    """Abstract market data provider for daily OHLCV bars."""

    @abstractmethod
    def fetch_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        tickers: list[str] | None = None,
    ) -> pd.DataFrame:
        """Fetch daily price bars."""
        raise NotImplementedError
