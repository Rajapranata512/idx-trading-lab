from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.universe.idx_archive import validate_universe_history


_PROVENANCE_COLUMNS = [
    "universe_eligible",
    "universe_exclusion_reason",
    "universe_indices",
    "universe_effective_from",
    "universe_effective_until",
    "universe_source",
    "universe_source_document",
]


def _market_date(value: Any, timezone: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT
    if pd.isna(parsed):
        return pd.NaT
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert(timezone).tz_localize(None)
    return parsed.normalize()


def _normalize_indexes(indexes: Iterable[str]) -> tuple[str, ...]:
    selected = tuple(
        sorted({str(value).upper().strip() for value in indexes if str(value).strip()})
    )
    invalid = sorted(set(selected) - {"LQ45", "IDX30"})
    if invalid:
        raise ValueError(f"Unsupported research universe indexes: {invalid}")
    if not selected:
        raise ValueError("At least one research universe index is required")
    return selected


def _load_history(history_path: str | Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = Path(history_path)
    if not path.exists():
        raise FileNotFoundError(f"Universe history not found: {path}")
    history = pd.read_csv(path)
    return validate_universe_history(history)


def annotate_point_in_time_universe(
    rows: pd.DataFrame,
    history_path: str | Path,
    *,
    indexes: Iterable[str] = ("LQ45", "IDX30"),
    date_column: str = "date",
    ticker_column: str = "ticker",
    timezone: str = "Asia/Jakarta",
    uncovered_policy: str = "error",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Annotate dated ticker rows with official point-in-time membership.

    The exclude policy retains uncovered rows with universe_eligible=False so
    callers can preserve outcome bars. It never substitutes the current
    universe for missing historical coverage.
    """

    missing = [
        column for column in [date_column, ticker_column] if column not in rows.columns
    ]
    if missing:
        raise ValueError(f"Research rows are missing columns: {missing}")

    policy = str(uncovered_policy).lower().strip()
    if policy not in {"error", "exclude"}:
        raise ValueError("uncovered_policy must be 'error' or 'exclude'")
    selected_indexes = _normalize_indexes(indexes)
    history, history_summary = _load_history(history_path)

    frame = rows.drop(columns=_PROVENANCE_COLUMNS, errors="ignore").copy()
    frame["_research_row_id"] = range(len(frame))
    frame["_research_date"] = pd.to_datetime(
        frame[date_column].map(lambda value: _market_date(value, timezone)),
        errors="coerce",
    )
    frame["_research_ticker"] = (
        frame[ticker_column].astype(str).str.upper().str.strip()
    )

    invalid_dates = frame["_research_date"].isna()
    invalid_tickers = frame["_research_ticker"].eq("") | frame[
        "_research_ticker"
    ].eq("NAN")
    if bool(invalid_dates.any()) or bool(invalid_tickers.any()):
        raise ValueError(
            "Research rows contain invalid dates or tickers: "
            f"invalid_dates={int(invalid_dates.sum())}, "
            f"invalid_tickers={int(invalid_tickers.sum())}"
        )

    frame["universe_eligible"] = False
    frame["universe_exclusion_reason"] = "uncovered_date"
    frame["universe_indices"] = ""
    frame["universe_effective_from"] = ""
    frame["universe_effective_until"] = ""
    frame["universe_source"] = ""
    frame["universe_source_document"] = ""

    periods = (
        history[["effective_from", "effective_until"]]
        .drop_duplicates()
        .sort_values(["effective_from", "effective_until"])
        .reset_index(drop=True)
    )
    for period in periods.itertuples(index=False):
        start = pd.Timestamp(period.effective_from)
        end = pd.Timestamp(period.effective_until)
        date_mask = frame["_research_date"].between(start, end, inclusive="both")
        if not bool(date_mask.any()):
            continue

        period_rows = history[
            history["effective_from"].eq(start.date().isoformat())
            & history["effective_until"].eq(end.date().isoformat())
            & history["index"].isin(selected_indexes)
        ]
        memberships = period_rows.groupby("ticker")["index"].agg(
            lambda values: ",".join(sorted(set(values)))
        )
        source = str(period_rows["source"].iloc[0])
        source_document = str(period_rows["source_document"].iloc[0])

        frame.loc[date_mask, "universe_exclusion_reason"] = "not_member"
        frame.loc[date_mask, "universe_effective_from"] = start.date().isoformat()
        frame.loc[date_mask, "universe_effective_until"] = end.date().isoformat()
        frame.loc[date_mask, "universe_source"] = source
        frame.loc[date_mask, "universe_source_document"] = source_document
        frame.loc[date_mask, "universe_indices"] = frame.loc[
            date_mask, "_research_ticker"
        ].map(memberships).fillna("")

        eligible_mask = date_mask & frame["universe_indices"].ne("")
        frame.loc[eligible_mask, "universe_eligible"] = True
        frame.loc[eligible_mask, "universe_exclusion_reason"] = ""

    uncovered_mask = frame["universe_exclusion_reason"].eq("uncovered_date")
    non_member_mask = frame["universe_exclusion_reason"].eq("not_member")
    uncovered_dates = sorted(
        frame.loc[uncovered_mask, "_research_date"]
        .dt.date.astype(str)
        .drop_duplicates()
        .tolist()
    )
    non_member_tickers = sorted(
        frame.loc[non_member_mask, "_research_ticker"].drop_duplicates().tolist()
    )
    uncovered_date_preview = (
        uncovered_dates
        if len(uncovered_dates) <= 20
        else [*uncovered_dates[:10], *uncovered_dates[-10:]]
    )
    input_dates = frame["_research_date"].drop_duplicates().sort_values()
    eligible = frame["universe_eligible"].astype(bool)
    diagnostics = {
        "schema_version": 1,
        "status": "ok" if bool(eligible.any()) else "no_eligible_rows",
        "history_path": str(Path(history_path)),
        "indexes": list(selected_indexes),
        "timezone": timezone,
        "input_rows": int(len(frame)),
        "eligible_rows": int(eligible.sum()),
        "excluded_rows": int((~eligible).sum()),
        "excluded_uncovered_rows": int(uncovered_mask.sum()),
        "excluded_non_member_rows": int(non_member_mask.sum()),
        "input_unique_dates": int(frame["_research_date"].nunique()),
        "input_unique_tickers": int(frame["_research_ticker"].nunique()),
        "eligible_unique_dates": int(frame.loc[eligible, "_research_date"].nunique()),
        "eligible_unique_tickers": int(
            frame.loc[eligible, "_research_ticker"].nunique()
        ),
        "input_date_min": (
            pd.Timestamp(input_dates.iloc[0]).date().isoformat()
            if not input_dates.empty
            else ""
        ),
        "input_date_max": (
            pd.Timestamp(input_dates.iloc[-1]).date().isoformat()
            if not input_dates.empty
            else ""
        ),
        "coverage_effective_from": history_summary["earliest_effective_from"],
        "coverage_effective_until": history_summary["latest_effective_until"],
        "source_period_count": history_summary["period_count"],
        "source_document_count": history_summary["source_document_count"],
        "excluded_uncovered_dates_count": len(uncovered_dates),
        "excluded_uncovered_date_min": (
            uncovered_dates[0] if uncovered_dates else ""
        ),
        "excluded_uncovered_date_max": (
            uncovered_dates[-1] if uncovered_dates else ""
        ),
        "excluded_uncovered_dates_preview": uncovered_date_preview,
        "excluded_uncovered_dates_truncated": len(uncovered_dates) > 20,
        "excluded_non_member_tickers": non_member_tickers,
        "current_universe_substitution": False,
        "final_execution_eligible": False,
    }

    if uncovered_dates and policy == "error":
        preview = uncovered_dates[:5]
        raise ValueError(
            "Research rows contain dates outside official universe coverage: "
            f"count={len(uncovered_dates)}, preview={preview}"
        )

    frame = frame.sort_values("_research_row_id").drop(
        columns=["_research_row_id", "_research_date", "_research_ticker"]
    )
    frame[ticker_column] = frame[ticker_column].astype(str).str.upper().str.strip()
    frame.attrs["point_in_time_universe"] = diagnostics
    return frame.reset_index(drop=True), diagnostics


def filter_point_in_time_universe(
    rows: pd.DataFrame,
    history_path: str | Path,
    *,
    indexes: Iterable[str] = ("LQ45", "IDX30"),
    date_column: str = "date",
    ticker_column: str = "ticker",
    timezone: str = "Asia/Jakarta",
    uncovered_policy: str = "error",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    annotated, diagnostics = annotate_point_in_time_universe(
        rows,
        history_path,
        indexes=indexes,
        date_column=date_column,
        ticker_column=ticker_column,
        timezone=timezone,
        uncovered_policy=uncovered_policy,
    )
    eligible = annotated[annotated["universe_eligible"].astype(bool)].copy()
    eligible.attrs["point_in_time_universe"] = diagnostics
    return eligible.reset_index(drop=True), diagnostics
