from __future__ import annotations

import pandas as pd

from src.config import Settings
from src.ingest.providers.csv_provider import CSVProvider
from src.ingest.providers.rest_provider import RestEodProvider
from src.ingest.providers.yfinance_provider import YFinanceProvider
from src.ingest.validator import validate_prices

REQUIRED_COLS = ["date", "ticker", "open", "high", "low", "close", "volume"]


def load_prices_csv(path: str, source: str = "csv") -> pd.DataFrame:
    """Load daily OHLCV data from local CSV and validate canonical output."""
    df = pd.read_csv(path)
    canonical, _ = validate_prices(df, source=source, max_staleness_days=10000)
    return canonical


def load_prices_from_provider(
    settings: Settings,
    start_date: str | None = None,
    end_date: str | None = None,
    tickers: list[str] | None = None,
) -> tuple[pd.DataFrame, str]:
    """Load daily prices using primary provider and fallback to CSV on failure."""
    provider_kind = settings.data.provider.kind.lower()

    if provider_kind == "rest":
        primary = RestEodProvider(settings.data.provider.rest)
        try:
            raw = primary.fetch_daily(start_date=start_date, end_date=end_date, tickers=tickers)
            canonical, _ = validate_prices(raw, source="rest")
            return canonical, "rest"
        except Exception:
            if settings.data.provider.yfinance_fallback_enabled:
                try:
                    yf_provider = YFinanceProvider(settings.data.provider.yfinance_ticker_suffix)
                    raw = yf_provider.fetch_daily(start_date=start_date, end_date=end_date, tickers=tickers)
                    canonical, _ = validate_prices(raw, source="yfinance_fallback")
                    return canonical, "yfinance_fallback"
                except Exception:
                    pass
            fallback = CSVProvider(settings.data.fallback_csv_path)
            raw = fallback.fetch_daily(start_date=start_date, end_date=end_date, tickers=tickers)
            canonical, _ = validate_prices(raw, source="csv_fallback")
            return canonical, "csv_fallback"

    if provider_kind == "csv":
        provider = CSVProvider(settings.data.canonical_prices_path)
        raw = provider.fetch_daily(start_date=start_date, end_date=end_date, tickers=tickers)
        canonical, _ = validate_prices(raw, source="csv")
        return canonical, "csv"

    raise ValueError(f"Unknown provider kind: {settings.data.provider.kind}")
