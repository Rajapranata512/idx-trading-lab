from __future__ import annotations

from datetime import date
from io import BytesIO
from itertools import product
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import pytest

from src.config import load_settings
from src.universe import (
    active_universe_from_history,
    import_idx_universe_archive,
    maybe_auto_update_universe,
)


def _tickers(count: int, offset: int = 0) -> list[str]:
    values = ["".join(chars) for chars in product("ABCDEFGHIJKLMNOPQRSTUVWXYZ", repeat=4)]
    return values[offset : offset + count]


def _history_rows(
    effective_from: str,
    effective_until: str,
    lq45_count: int = 45,
    idx30_count: int = 30,
) -> list[dict[str, str]]:
    lq45 = _tickers(lq45_count)
    idx30 = lq45[:idx30_count]
    rows: list[dict[str, str]] = []
    for index_name, members in [("LQ45", lq45), ("IDX30", idx30)]:
        rows.extend(
            {
                "ticker": ticker,
                "index": index_name,
                "effective_from": effective_from,
                "effective_until": effective_until,
                "source": "IDX_OFFICIAL_ANNOUNCEMENT",
                "source_document": "https://www.idx.co.id/official.zip",
                "imported_at": "2026-04-24T12:00:00Z",
            }
            for ticker in members
        )
    return rows


def _settings(tmp_path: Path):
    settings = load_settings("config/settings.json")
    settings.data.universe_csv_path = str(tmp_path / "universe.csv")
    settings.data.universe_auto_update.history_path = str(tmp_path / "history.csv")
    settings.data.universe_auto_update.state_path = str(tmp_path / "state.json")
    settings.data.universe_auto_update.fail_on_error = True
    settings.data.universe_auto_update.fail_on_stale = True
    return settings


def test_point_in_time_universe_activates_exact_member_counts(tmp_path):
    settings = _settings(tmp_path)
    pd.DataFrame(
        _history_rows("2026-05-04", "2026-07-31")
    ).to_csv(settings.data.universe_auto_update.history_path, index=False)

    result = maybe_auto_update_universe(
        settings=settings,
        force=True,
        as_of=date(2026, 7, 20),
    )

    assert result["status"] == "updated_from_history"
    assert result["counts"] == {"lq45": 45, "idx30": 30, "combined": 45}
    assert result["effective_until"] == "2026-07-31"
    active = pd.read_csv(settings.data.universe_csv_path)
    assert active["ticker"].nunique() == 45
    assert active["effective_from"].eq("2026-05-04").all()


def test_tracked_history_contains_current_august_2026_snapshot():
    active, metadata = active_universe_from_history(
        history_path="data/reference/universe_history.csv",
        as_of=date(2026, 8, 10),
        expected_lq45=45,
        expected_idx30=30,
    )

    assert metadata["effective_from"] == "2026-08-03"
    assert metadata["effective_until"] == "2026-10-30"
    assert metadata["counts"] == {"lq45": 45, "idx30": 30, "combined": 45}
    assert active["ticker"].nunique() == 45
    assert {"INDY", "NCKL"} <= set(active["ticker"])


def test_point_in_time_universe_blocks_expired_snapshot(tmp_path):
    settings = _settings(tmp_path)
    pd.DataFrame(
        _history_rows("2026-05-04", "2026-07-19")
    ).to_csv(settings.data.universe_auto_update.history_path, index=False)

    with pytest.raises(RuntimeError, match="Universe freshness gate blocked run"):
        maybe_auto_update_universe(
            settings=settings,
            force=True,
            as_of=date(2026, 7, 20),
        )


def test_point_in_time_universe_rejects_wrong_lq45_count(tmp_path):
    settings = _settings(tmp_path)
    pd.DataFrame(
        _history_rows("2026-05-04", "2026-07-31", lq45_count=44)
    ).to_csv(settings.data.universe_auto_update.history_path, index=False)

    with pytest.raises(RuntimeError, match="expected 45"):
        maybe_auto_update_universe(
            settings=settings,
            force=True,
            as_of=date(2026, 7, 20),
        )


def _workbook(index_name: str, count: int) -> bytes:
    rows = [
        [None, f"Lampiran Pengumuman IDX {index_name}", None],
        [None, "Nama Indeks", index_name],
        [None, "Periode Efektif Konstituen", "04 Mei 2026 s.d. 31 Juli 2026"],
    ]
    rows.extend([[None, None, None] for _ in range(6)])
    rows.extend([[None, number, ticker] for number, ticker in enumerate(_tickers(count), start=1)])
    buffer = BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, header=False)
    return buffer.getvalue()


def test_import_official_idx_archive_writes_history(tmp_path):
    archive = tmp_path / "official.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr("1 Lamp - IDX30 - Mayor.xlsx", _workbook("IDX30", 30))
        bundle.writestr("2 Lamp - LQ45 - Mayor.xlsx", _workbook("LQ45", 45))

    result = import_idx_universe_archive(
        archive_path=archive,
        history_path=tmp_path / "history.csv",
        source_document="https://www.idx.co.id/official.zip",
    )

    assert result["counts"] == {"lq45": 45, "idx30": 30, "combined": 45}
    assert result["effective_from"] == "2026-05-04"
    assert result["effective_until"] == "2026-07-31"
    history = pd.read_csv(tmp_path / "history.csv")
    assert len(history) == 75
