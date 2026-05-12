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

    def fetch_intraday(
        self,
        timeframe: str,
        start_datetime: str | None = None,
        end_datetime: str | None = None,
        tickers: list[str] | None = None,
        max_rows_per_ticker: int = 500,
    ) -> pd.DataFrame:
        """Fetch intraday OHLCV bars.

        Providers can override this to support polling/websocket feeds.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support intraday fetch")
