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


@pytest.mark.parametrize(
    ("as_of", "expected_from", "expected_until"),
    [
        (date(2024, 11, 15), "2024-11-01", "2025-01-31"),
        (date(2025, 2, 10), "2025-02-03", "2025-04-30"),
        (date(2025, 5, 10), "2025-05-02", "2025-07-31"),
        (date(2025, 8, 10), "2025-08-01", "2025-10-31"),
        (date(2025, 11, 10), "2025-11-03", "2026-01-30"),
        (date(2026, 2, 10), "2026-02-02", "2026-04-30"),
        (date(2026, 5, 10), "2026-05-04", "2026-07-31"),
        (date(2026, 8, 10), "2026-08-03", "2026-10-30"),
    ],
)
def test_tracked_history_resolves_each_official_period(
    as_of,
    expected_from,
    expected_until,
):
    active, metadata = active_universe_from_history(
        history_path="data/reference/universe_history.csv",
        as_of=as_of,
        expected_lq45=45,
        expected_idx30=30,
    )

    assert metadata["effective_from"] == expected_from
    assert metadata["effective_until"] == expected_until
    assert metadata["counts"] == {"lq45": 45, "idx30": 30, "combined": 45}
    assert active["ticker"].nunique() == 45


def test_tracked_history_has_traceable_non_overlapping_official_periods():
    history = pd.read_csv("data/reference/universe_history.csv")
    periods = history[["effective_from", "effective_until"]].drop_duplicates()

    assert len(history) == 600
    assert len(periods) == 8
    assert history["source_document"].nunique() == 8
    assert history["source"].eq("IDX_OFFICIAL_ANNOUNCEMENT").all()
    assert history["source_document"].str.startswith(
        ("https://www.idx.id/", "https://www.idx.co.id/")
    ).all()
    assert pd.to_datetime(
        history["imported_at"],
        errors="coerce",
        format="mixed",
        utc=True,
    ).notna().all()

    previous_end = None
    for period in periods.sort_values("effective_from").itertuples(index=False):
        start = pd.Timestamp(period.effective_from)
        end = pd.Timestamp(period.effective_until)
        assert previous_end is None or start > previous_end
        previous_end = end

        rows = history[
            history["effective_from"].eq(period.effective_from)
            & history["effective_until"].eq(period.effective_until)
        ]
        lq45 = set(rows.loc[rows["index"].eq("LQ45"), "ticker"])
        idx30 = set(rows.loc[rows["index"].eq("IDX30"), "ticker"])
        assert len(lq45) == 45
        assert len(idx30) == 30
        assert idx30 <= lq45
        assert rows["source_document"].nunique() == 1


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
    assert result["history"] == {
        "rows": 75,
        "period_count": 1,
        "earliest_effective_from": "2026-05-04",
        "latest_effective_until": "2026-07-31",
        "source_document_count": 1,
    }
    history = pd.read_csv(tmp_path / "history.csv")
    assert len(history) == 75

    repeated = import_idx_universe_archive(
        archive_path=archive,
        history_path=tmp_path / "history.csv",
        source_document="https://www.idx.id/official.zip",
    )
    repeated_history = pd.read_csv(tmp_path / "history.csv")

    assert repeated["history"]["rows"] == 75
    assert repeated_history.duplicated(
        subset=["ticker", "index", "effective_from", "effective_until"]
    ).sum() == 0
    assert set(repeated_history["source_document"]) == {
        "https://www.idx.id/official.zip"
    }


def test_import_official_idx_archive_rejects_overlapping_history(tmp_path):
    archive = tmp_path / "official.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr("1 Lamp - IDX30 - Mayor.xlsx", _workbook("IDX30", 30))
        bundle.writestr("2 Lamp - LQ45 - Mayor.xlsx", _workbook("LQ45", 45))

    existing = pd.DataFrame(
        _history_rows("2026-04-01", "2026-05-31")
    )
    existing.to_csv(tmp_path / "history.csv", index=False)

    with pytest.raises(ValueError, match="overlapping effective periods"):
        import_idx_universe_archive(
            archive_path=archive,
            history_path=tmp_path / "history.csv",
            source_document="https://www.idx.id/official.zip",
        )
