from __future__ import annotations

from datetime import datetime
from itertools import product
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def official_universe_history(tmp_path: Path) -> Path:
    generated = [
        "".join(chars)
        for chars in product("ABCDEFGHIJKLMNOPQRSTUVWXYZ", repeat=4)
    ]
    lq45 = ["AAAA", "BBBB", *[ticker for ticker in generated if ticker not in {"AAAA", "BBBB"}]][:45]
    rows: list[dict[str, str]] = []
    for index_name, members in [("LQ45", lq45), ("IDX30", lq45[:30])]:
        rows.extend(
            {
                "ticker": ticker,
                "index": index_name,
                "effective_from": "2026-01-01",
                "effective_until": "2026-01-31",
                "source": "IDX_OFFICIAL_ANNOUNCEMENT",
                "source_document": "https://www.idx.id/test-period.zip",
                "imported_at": "2026-08-14T12:00:00Z",
            }
            for ticker in members
        )
    path = tmp_path / "universe_history.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


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
