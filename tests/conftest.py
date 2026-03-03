from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest


@pytest.fixture
def sample_prices_df() -> pd.DataFrame:
    end = pd.Timestamp(datetime.utcnow().date())
    dates = pd.date_range(end=end, periods=80, freq="D")
    rows: list[dict] = []
    for ticker, base, vol in [("BBCA", 10000, 1_200_000), ("TLKM", 3500, 5_000_000), ("BMRI", 6000, 3_000_000)]:
        for i, date in enumerate(dates):
            close = base + i * 5
            rows.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "ticker": ticker,
                    "open": close - 20,
                    "high": close + 30,
                    "low": close - 40,
                    "close": close,
                    "volume": vol + (i * 1000),
                }
            )
    return pd.DataFrame(rows)
