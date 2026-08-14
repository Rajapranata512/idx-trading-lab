from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

import pandas as pd


_MONTHS_ID = {
    "januari": 1,
    "februari": 2,
    "maret": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "agustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "desember": 12,
}
_PERIOD_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s+s\.?d\.?\s+"
    r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    flags=re.IGNORECASE,
)
_TICKER_RE = re.compile(r"^[A-Z]{4,6}$")
_EXPECTED_MEMBERS = {"LQ45": 45, "IDX30": 30}
_HISTORY_COLUMNS = [
    "ticker",
    "index",
    "effective_from",
    "effective_until",
    "source",
    "source_document",
    "imported_at",
]


def _parse_id_date(day: str, month: str, year: str) -> pd.Timestamp:
    month_number = _MONTHS_ID.get(month.strip().lower())
    if month_number is None:
        raise ValueError(f"Unsupported Indonesian month in IDX workbook: {month}")
    return pd.Timestamp(year=int(year), month=month_number, day=int(day))


def _extract_effective_period(frame: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    for value in frame.head(12).astype(str).to_numpy().ravel().tolist():
        match = _PERIOD_RE.search(str(value))
        if match:
            start = _parse_id_date(match.group(1), match.group(2), match.group(3))
            end = _parse_id_date(match.group(4), match.group(5), match.group(6))
            if end < start:
                raise ValueError("IDX workbook effective period ends before it starts")
            return start, end
    raise ValueError("IDX workbook effective constituent period was not found")


def parse_idx_constituent_workbook(
    workbook_bytes: bytes,
    index_name: str,
    expected_members: int | None = None,
) -> tuple[list[str], pd.Timestamp, pd.Timestamp]:
    normalized_index = str(index_name).strip().upper()
    expected = int(expected_members or _EXPECTED_MEMBERS.get(normalized_index, 0))
    if expected <= 0:
        raise ValueError(f"Expected member count is required for index {normalized_index}")

    frame = pd.read_excel(BytesIO(workbook_bytes), header=None)
    header_text = " ".join(frame.head(8).astype(str).to_numpy().ravel().tolist()).upper()
    if normalized_index not in header_text:
        raise ValueError(f"Workbook does not identify itself as {normalized_index}")

    effective_from, effective_until = _extract_effective_period(frame)
    members: list[str] = []
    next_number = 1
    for _, row in frame.iterrows():
        row_number = pd.to_numeric(row.iloc[1] if len(row) > 1 else None, errors="coerce")
        if pd.isna(row_number) or int(row_number) != next_number:
            continue
        ticker = str(row.iloc[2] if len(row) > 2 else "").strip().upper()
        if not _TICKER_RE.fullmatch(ticker):
            continue
        members.append(ticker)
        next_number += 1
        if len(members) == expected:
            break

    if len(members) != expected:
        raise ValueError(
            f"{normalized_index} workbook contains {len(members)} members; expected {expected}"
        )
    if len(set(members)) != expected:
        raise ValueError(f"{normalized_index} workbook contains duplicate members")
    return members, effective_from, effective_until


def _find_workbook_name(names: list[str], index_name: str) -> str:
    normalized = index_name.upper()
    matches = [
        name
        for name in names
        if name.lower().endswith(".xlsx")
        and re.search(rf"(^|[^A-Z0-9]){re.escape(normalized)}([^A-Z0-9]|$)", name.upper())
    ]
    if len(matches) != 1:
        raise ValueError(
            f"IDX archive must contain exactly one {normalized} workbook; found {len(matches)}"
        )
    return matches[0]


def _validate_universe_history(
    history: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    missing = [column for column in _HISTORY_COLUMNS if column not in history.columns]
    if missing:
        raise ValueError(f"Universe history is missing columns: {missing}")

    frame = history[_HISTORY_COLUMNS].copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["index"] = frame["index"].astype(str).str.upper().str.strip()
    frame["source"] = frame["source"].astype(str).str.strip()
    frame["source_document"] = frame["source_document"].astype(str).str.strip()
    frame["imported_at"] = frame["imported_at"].astype(str).str.strip()
    frame["effective_from"] = pd.to_datetime(
        frame["effective_from"],
        errors="coerce",
    )
    frame["effective_until"] = pd.to_datetime(
        frame["effective_until"],
        errors="coerce",
    )
    imported_at = pd.to_datetime(
        frame["imported_at"],
        errors="coerce",
        format="mixed",
        utc=True,
    )
    invalid_conditions = pd.DataFrame(
        {
            "ticker": ~frame["ticker"].str.fullmatch(_TICKER_RE),
            "index": ~frame["index"].isin(_EXPECTED_MEMBERS),
            "effective_from": frame["effective_from"].isna(),
            "effective_until": frame["effective_until"].isna()
            | frame["effective_until"].lt(frame["effective_from"]),
            "source": frame["source"].ne("IDX_OFFICIAL_ANNOUNCEMENT"),
            "source_document": ~frame["source_document"].str.startswith(
                ("https://www.idx.id/", "https://www.idx.co.id/")
            ),
            "imported_at": imported_at.isna(),
        },
        index=frame.index,
    )
    invalid = invalid_conditions.any(axis=1)
    if bool(invalid.any()):
        sample = frame.loc[
            invalid,
            [
                "ticker",
                "index",
                "effective_from",
                "effective_until",
                "source",
                "source_document",
                "imported_at",
            ],
        ].head(3)
        sample["invalid_fields"] = [
            ",".join(invalid_conditions.columns[conditions].tolist())
            for _, conditions in invalid_conditions.loc[sample.index].iterrows()
        ]
        raise ValueError(
            "Universe history contains invalid or untraceable rows. Sample: "
            + sample.astype(str).to_json(orient="records")
        )

    duplicate = frame.duplicated(
        subset=["ticker", "index", "effective_from", "effective_until"],
        keep=False,
    )
    if bool(duplicate.any()):
        raise ValueError("Universe history contains duplicate membership rows")

    periods = (
        frame[["effective_from", "effective_until"]]
        .drop_duplicates()
        .sort_values(["effective_from", "effective_until"])
        .reset_index(drop=True)
    )
    previous_end: pd.Timestamp | None = None
    for period in periods.itertuples(index=False):
        start = pd.Timestamp(period.effective_from)
        end = pd.Timestamp(period.effective_until)
        if previous_end is not None and start <= previous_end:
            raise ValueError("Universe history contains overlapping effective periods")
        previous_end = end

        period_rows = frame[
            frame["effective_from"].eq(start)
            & frame["effective_until"].eq(end)
        ]
        lq45 = set(period_rows.loc[period_rows["index"].eq("LQ45"), "ticker"])
        idx30 = set(period_rows.loc[period_rows["index"].eq("IDX30"), "ticker"])
        if len(lq45) != _EXPECTED_MEMBERS["LQ45"]:
            raise ValueError(
                f"LQ45 period {start.date()} has {len(lq45)} members; expected 45"
            )
        if len(idx30) != _EXPECTED_MEMBERS["IDX30"]:
            raise ValueError(
                f"IDX30 period {start.date()} has {len(idx30)} members; expected 30"
            )
        if not idx30.issubset(lq45):
            raise ValueError(
                f"IDX30 period {start.date()} contains members outside LQ45"
            )
        if period_rows["source_document"].nunique() != 1:
            raise ValueError(
                f"Universe period {start.date()} has conflicting source documents"
            )

    frame["effective_from"] = frame["effective_from"].dt.date.astype(str)
    frame["effective_until"] = frame["effective_until"].dt.date.astype(str)
    frame = frame.sort_values(["effective_from", "index", "ticker"]).reset_index(
        drop=True
    )
    summary = {
        "rows": int(len(frame)),
        "period_count": int(len(periods)),
        "earliest_effective_from": (
            pd.Timestamp(periods.iloc[0]["effective_from"]).date().isoformat()
            if not periods.empty
            else ""
        ),
        "latest_effective_until": (
            pd.Timestamp(periods.iloc[-1]["effective_until"]).date().isoformat()
            if not periods.empty
            else ""
        ),
        "source_document_count": int(frame["source_document"].nunique()),
    }
    return frame, summary


def import_idx_universe_archive(
    archive_path: str | Path,
    history_path: str | Path,
    source_document: str = "",
) -> dict[str, Any]:
    archive = Path(archive_path)
    if not archive.exists():
        raise FileNotFoundError(f"IDX universe archive not found: {archive}")

    try:
        with ZipFile(archive) as bundle:
            names = bundle.namelist()
            parsed: dict[str, tuple[list[str], pd.Timestamp, pd.Timestamp]] = {}
            for index_name, expected in _EXPECTED_MEMBERS.items():
                workbook_name = _find_workbook_name(names, index_name)
                parsed[index_name] = parse_idx_constituent_workbook(
                    bundle.read(workbook_name),
                    index_name=index_name,
                    expected_members=expected,
                )
    except BadZipFile as exc:
        raise ValueError(f"IDX universe archive is not a valid ZIP: {archive}") from exc

    periods = {(values[1].date(), values[2].date()) for values in parsed.values()}
    if len(periods) != 1:
        raise ValueError("LQ45 and IDX30 workbooks have different effective periods")
    effective_from, effective_until = next(iter(periods))

    imported_at = pd.Timestamp.utcnow().isoformat()
    source = "IDX_OFFICIAL_ANNOUNCEMENT"
    document = source_document.strip() or archive.name
    rows: list[dict[str, Any]] = []
    for index_name, (members, _, _) in parsed.items():
        rows.extend(
            {
                "ticker": ticker,
                "index": index_name,
                "effective_from": effective_from.isoformat(),
                "effective_until": effective_until.isoformat(),
                "source": source,
                "source_document": document,
                "imported_at": imported_at,
            }
            for ticker in members
        )

    history_file = Path(history_path)
    columns = list(_HISTORY_COLUMNS)
    incoming = pd.DataFrame(rows, columns=columns)
    if history_file.exists():
        existing = pd.read_csv(history_file)
        missing = [column for column in columns if column not in existing.columns]
        if missing:
            raise ValueError(f"Universe history is missing columns: {missing}")
        existing = existing[columns].copy()
        existing = existing[
            ~(
                existing["index"].astype(str).str.upper().isin(_EXPECTED_MEMBERS)
                & existing["effective_from"].astype(str).eq(effective_from.isoformat())
                & existing["effective_until"].astype(str).eq(effective_until.isoformat())
            )
        ]
        combined = pd.concat([existing, incoming], ignore_index=True)
    else:
        combined = incoming

    combined["ticker"] = combined["ticker"].astype(str).str.upper().str.strip()
    combined["index"] = combined["index"].astype(str).str.upper().str.strip()
    combined = combined.drop_duplicates(
        subset=["ticker", "index", "effective_from", "effective_until"],
        keep="last",
    )
    combined, history_summary = _validate_universe_history(combined)

    history_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = history_file.with_suffix(history_file.suffix + ".tmp")
    combined.to_csv(tmp_path, index=False)
    tmp_path.replace(history_file)

    return {
        "status": "imported",
        "archive_path": str(archive),
        "history_path": str(history_file),
        "source_document": document,
        "effective_from": effective_from.isoformat(),
        "effective_until": effective_until.isoformat(),
        "counts": {
            "lq45": len(parsed["LQ45"][0]),
            "idx30": len(parsed["IDX30"][0]),
            "combined": len(set(parsed["LQ45"][0]) | set(parsed["IDX30"][0])),
        },
        "history": history_summary,
    }
