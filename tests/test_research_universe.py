from __future__ import annotations

from itertools import product
from pathlib import Path

import pandas as pd
import pytest

from src.universe import (
    annotate_point_in_time_universe,
    filter_point_in_time_universe,
)
from src.model_v2.labeling import build_training_dataset


def _tickers(count: int) -> list[str]:
    return [
        "".join(chars)
        for chars in product("ABCDEFGHIJKLMNOPQRSTUVWXYZ", repeat=4)
    ][:count]


def _period_rows(
    effective_from: str,
    effective_until: str,
    lq45: list[str],
    document: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index_name, members in [("LQ45", lq45), ("IDX30", lq45[:30])]:
        rows.extend(
            {
                "ticker": ticker,
                "index": index_name,
                "effective_from": effective_from,
                "effective_until": effective_until,
                "source": "IDX_OFFICIAL_ANNOUNCEMENT",
                "source_document": document,
                "imported_at": "2026-08-14T12:00:00Z",
            }
            for ticker in members
        )
    return rows


def _history_path(tmp_path: Path) -> tuple[Path, list[str], str]:
    first = _tickers(46)
    removed = first[44]
    added = first[45]
    rows = [
        *_period_rows(
            "2024-11-01",
            "2025-01-31",
            first[:45],
            "https://www.idx.id/period-1.zip",
        ),
        *_period_rows(
            "2025-02-03",
            "2025-04-30",
            [*first[:44], added],
            "https://www.idx.id/period-2.zip",
        ),
    ]
    path = tmp_path / "universe_history.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path, first, removed


def test_annotation_preserves_outcome_rows_and_marks_membership_changes(
    tmp_path: Path,
) -> None:
    history_path, tickers, removed = _history_path(tmp_path)
    added = tickers[45]
    rows = pd.DataFrame(
        [
            {"date": "2024-10-31", "ticker": tickers[0], "close": 100.0},
            {"date": "2025-01-31", "ticker": removed, "close": 101.0},
            {"date": "2025-02-01", "ticker": tickers[0], "close": 102.0},
            {"date": "2025-02-03", "ticker": removed, "close": 103.0},
            {"date": "2025-02-03", "ticker": added, "close": 104.0},
        ]
    )

    annotated, diagnostics = annotate_point_in_time_universe(
        rows,
        history_path,
        uncovered_policy="exclude",
    )

    assert len(annotated) == len(rows)
    assert diagnostics["input_rows"] == 5
    assert diagnostics["eligible_rows"] == 2
    assert diagnostics["excluded_uncovered_rows"] == 2
    assert diagnostics["excluded_non_member_rows"] == 1
    assert diagnostics["source_period_count"] == 2
    assert diagnostics["current_universe_substitution"] is False
    assert diagnostics["final_execution_eligible"] is False
    assert diagnostics["excluded_uncovered_dates_count"] == 2
    assert diagnostics["excluded_uncovered_dates_preview"] == [
        "2024-10-31",
        "2025-02-01",
    ]
    assert diagnostics["excluded_uncovered_dates_truncated"] is False
    assert diagnostics["excluded_non_member_tickers"] == [removed]

    removed_after_change = annotated[
        annotated["date"].eq("2025-02-03")
        & annotated["ticker"].eq(removed)
    ].iloc[0]
    assert bool(removed_after_change["universe_eligible"]) is False
    assert removed_after_change["universe_exclusion_reason"] == "not_member"

    added_row = annotated[
        annotated["date"].eq("2025-02-03")
        & annotated["ticker"].eq(added)
    ].iloc[0]
    assert bool(added_row["universe_eligible"]) is True
    assert added_row["universe_effective_from"] == "2025-02-03"
    assert added_row["universe_source_document"].endswith("period-2.zip")


def test_filter_returns_only_eligible_rows_with_diagnostics(tmp_path: Path) -> None:
    history_path, tickers, removed = _history_path(tmp_path)
    added = tickers[45]
    rows = pd.DataFrame(
        [
            {"date": "2025-01-31", "ticker": removed},
            {"date": "2025-02-03", "ticker": removed},
            {"date": "2025-02-03", "ticker": added},
        ]
    )

    filtered, diagnostics = filter_point_in_time_universe(
        rows,
        history_path,
        uncovered_policy="exclude",
    )

    assert filtered[["date", "ticker"]].to_dict(orient="records") == [
        {"date": "2025-01-31", "ticker": removed},
        {"date": "2025-02-03", "ticker": added},
    ]
    assert filtered["universe_eligible"].all()
    assert diagnostics["eligible_rows"] == 2
    assert diagnostics["excluded_non_member_rows"] == 1
    assert filtered.attrs["point_in_time_universe"] == diagnostics


def test_empty_research_rows_return_bounded_diagnostics(tmp_path: Path) -> None:
    history_path, _, _ = _history_path(tmp_path)

    annotated, diagnostics = annotate_point_in_time_universe(
        pd.DataFrame(columns=["date", "ticker"]),
        history_path,
        uncovered_policy="exclude",
    )

    assert annotated.empty
    assert diagnostics["status"] == "no_eligible_rows"
    assert diagnostics["input_rows"] == 0
    assert diagnostics["eligible_rows"] == 0
    assert diagnostics["excluded_rows"] == 0
    assert diagnostics["input_date_min"] == ""
    assert diagnostics["input_date_max"] == ""


def test_uncovered_dates_fail_closed_by_default(tmp_path: Path) -> None:
    history_path, tickers, _ = _history_path(tmp_path)
    rows = pd.DataFrame([{"date": "2024-10-31", "ticker": tickers[0]}])

    with pytest.raises(ValueError, match="outside official universe coverage"):
        filter_point_in_time_universe(rows, history_path)


def test_uncovered_date_diagnostics_are_bounded(tmp_path: Path) -> None:
    history_path, tickers, _ = _history_path(tmp_path)
    dates = pd.date_range("2024-10-01", periods=25, freq="D")
    rows = pd.DataFrame(
        {"date": dates, "ticker": [tickers[0]] * len(dates)}
    )

    _, diagnostics = annotate_point_in_time_universe(
        rows,
        history_path,
        uncovered_policy="exclude",
    )

    expected_dates = [date.strftime("%Y-%m-%d") for date in dates]
    assert diagnostics["excluded_uncovered_dates_count"] == 25
    assert diagnostics["excluded_uncovered_dates_preview"] == [
        *expected_dates[:10],
        *expected_dates[-10:],
    ]
    assert diagnostics["excluded_uncovered_dates_truncated"] is True


def test_missing_research_keys_and_overlapping_history_are_rejected(
    tmp_path: Path,
) -> None:
    history_path, tickers, _ = _history_path(tmp_path)
    with pytest.raises(ValueError, match="missing columns"):
        filter_point_in_time_universe(
            pd.DataFrame([{"date": "2025-01-02"}]),
            history_path,
        )

    overlapping = [
        *_period_rows(
            "2025-01-01",
            "2025-03-31",
            tickers[:45],
            "https://www.idx.id/period-a.zip",
        ),
        *_period_rows(
            "2025-03-01",
            "2025-05-31",
            tickers[:45],
            "https://www.idx.id/period-b.zip",
        ),
    ]
    pd.DataFrame(overlapping).to_csv(history_path, index=False)

    with pytest.raises(ValueError, match="overlapping effective periods"):
        filter_point_in_time_universe(
            pd.DataFrame([{"date": "2025-03-10", "ticker": tickers[0]}]),
            history_path,
        )


def test_model_labeling_filters_entries_but_preserves_future_outcome_bars(
    tmp_path: Path,
) -> None:
    history_path, _, removed = _history_path(tmp_path)
    scored_history = pd.DataFrame(
        [
            {
                "date": "2025-01-31",
                "ticker": removed,
                "mode": "t1",
                "score": 99.0,
                "open": 100.0,
                "high": 103.0,
                "low": 97.0,
                "close": 100.0,
                "atr_14": 5.0,
            },
            {
                "date": "2025-02-03",
                "ticker": removed,
                "mode": "t1",
                "score": 99.0,
                "open": 100.0,
                "high": 111.0,
                "low": 99.0,
                "close": 110.0,
                "atr_14": 5.0,
            },
        ]
    )

    labeled = build_training_dataset(
        scored_history,
        mode="t1",
        horizon_days=1,
        roundtrip_cost_pct=0.0,
        universe_history_path=history_path,
    )

    assert len(labeled) == 1
    assert labeled.iloc[0]["date"] == pd.Timestamp("2025-01-31")
    assert labeled.iloc[0]["ticker"] == removed
    assert labeled.iloc[0]["outcome"] == "tp_hit"
    assert int(labeled.iloc[0]["y"]) == 1
    diagnostics = labeled.attrs["point_in_time_universe"]
    assert diagnostics["eligible_rows"] == 1
    assert diagnostics["excluded_non_member_rows"] == 1
