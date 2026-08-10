from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import PriceQualitySettings


_PRICE_COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume"]
_ACTION_COLUMNS = [
    "ticker",
    "effective_date",
    "action_type",
    "ratio",
    "status",
    "source",
]
_EVENT_COLUMNS = ["ticker", "event_date", "event_type", "status", "source"]
_SPLIT_ACTIONS = {"stock_split", "reverse_split"}


def _empty_actions() -> pd.DataFrame:
    return pd.DataFrame(columns=_ACTION_COLUMNS)


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=_EVENT_COLUMNS)


def load_corporate_actions(path: str | Path) -> pd.DataFrame:
    action_path = Path(path)
    if not action_path.exists():
        return _empty_actions()

    frame = pd.read_csv(action_path)
    missing = [column for column in _ACTION_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Corporate-action reference is missing columns: {missing}")

    actions = frame[_ACTION_COLUMNS].copy()
    actions["ticker"] = actions["ticker"].fillna("").astype(str).str.upper().str.strip()
    actions["effective_date"] = pd.to_datetime(actions["effective_date"], errors="coerce")
    actions["action_type"] = actions["action_type"].fillna("").astype(str).str.lower().str.strip()
    actions["ratio"] = pd.to_numeric(actions["ratio"], errors="coerce")
    actions["status"] = actions["status"].fillna("").astype(str).str.lower().str.strip()
    actions["source"] = actions["source"].fillna("").astype(str).str.strip()

    invalid = (
        actions["ticker"].str.fullmatch(r"[A-Z]{4,6}").fillna(False).eq(False)
        | actions["effective_date"].isna()
        | actions["action_type"].eq("")
        | actions["ratio"].isna()
        | actions["ratio"].le(0)
        | actions["status"].eq("")
        | actions["source"].eq("")
    )
    if bool(invalid.any()):
        sample = actions.loc[invalid].head(5).astype(str).to_dict(orient="records")
        raise ValueError(
            "Corporate-action reference contains invalid rows. Sample: "
            + json.dumps(sample, ensure_ascii=True)
        )
    return actions.sort_values(["ticker", "effective_date"]).reset_index(drop=True)


def load_verified_price_events(path: str | Path) -> pd.DataFrame:
    event_path = Path(path)
    if not event_path.exists():
        return _empty_events()

    frame = pd.read_csv(event_path)
    missing = [column for column in _EVENT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Verified price-event reference is missing columns: {missing}")

    events = frame[_EVENT_COLUMNS].copy()
    events["ticker"] = events["ticker"].fillna("").astype(str).str.upper().str.strip()
    events["event_date"] = pd.to_datetime(events["event_date"], errors="coerce")
    events["event_type"] = events["event_type"].fillna("").astype(str).str.lower().str.strip()
    events["status"] = events["status"].fillna("").astype(str).str.lower().str.strip()
    events["source"] = events["source"].fillna("").astype(str).str.strip()
    invalid = (
        events["ticker"].str.fullmatch(r"[A-Z]{4,6}").fillna(False).eq(False)
        | events["event_date"].isna()
        | events["event_type"].eq("")
        | events["status"].eq("")
        | events["source"].eq("")
    )
    if bool(invalid.any()):
        sample = events.loc[invalid].head(5).astype(str).to_dict(orient="records")
        raise ValueError(
            "Verified price-event reference contains invalid rows. Sample: "
            + json.dumps(sample, ensure_ascii=True)
        )
    return events.sort_values(["ticker", "event_date"]).reset_index(drop=True)


def build_split_adjusted_prices(
    raw_prices: pd.DataFrame,
    corporate_actions: pd.DataFrame,
) -> pd.DataFrame:
    missing = [column for column in _PRICE_COLUMNS if column not in raw_prices.columns]
    if missing:
        raise ValueError(f"Raw prices are missing columns required for adjustment: {missing}")

    adjusted = raw_prices.copy()
    adjusted["date"] = pd.to_datetime(adjusted["date"], errors="coerce")
    adjusted["ticker"] = adjusted["ticker"].astype(str).str.upper().str.strip()
    for column in ["open", "high", "low", "close", "volume"]:
        adjusted[column] = pd.to_numeric(adjusted[column], errors="coerce")
    adjusted["adjustment_factor"] = 1.0
    adjusted["price_basis"] = "raw"

    if corporate_actions.empty:
        return adjusted.sort_values(["ticker", "date"]).reset_index(drop=True)

    confirmed = corporate_actions[
        corporate_actions["status"].eq("confirmed")
        & corporate_actions["action_type"].isin(_SPLIT_ACTIONS)
    ].copy()
    for _, action in confirmed.iterrows():
        ticker = str(action["ticker"])
        effective_date = pd.Timestamp(action["effective_date"])
        ratio = float(action["ratio"])
        mask = adjusted["ticker"].eq(ticker) & adjusted["date"].lt(effective_date)
        if not bool(mask.any()):
            continue
        adjusted.loc[mask, ["open", "high", "low", "close"]] = (
            adjusted.loc[mask, ["open", "high", "low", "close"]] / ratio
        )
        adjusted.loc[mask, "volume"] = adjusted.loc[mask, "volume"] * ratio
        adjusted.loc[mask, "adjustment_factor"] = (
            adjusted.loc[mask, "adjustment_factor"] * ratio
        )
        adjusted.loc[mask, "price_basis"] = "split_adjusted"

    return adjusted.sort_values(["ticker", "date"]).reset_index(drop=True)


def classify_price_anomalies(
    prices: pd.DataFrame,
    corporate_actions: pd.DataFrame,
    threshold_pct: float,
    quarantine_days: int,
    verified_events: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    work = prices[_PRICE_COLUMNS].copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["ticker"] = work["ticker"].astype(str).str.upper().str.strip()
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.sort_values(["ticker", "date"])
    work["prev_close"] = work.groupby("ticker")["close"].shift(1)
    work["change_pct"] = (
        (work["close"] - work["prev_close"]) / work["prev_close"] * 100.0
    )
    anomaly = work[
        work["prev_close"].gt(0)
        & work["change_pct"].abs().gt(float(threshold_pct))
    ].copy()

    columns = [
        "ticker",
        "date",
        "prev_close",
        "close",
        "change_pct",
        "resolved",
        "resolved_by_action",
        "action_type",
        "action_effective_date",
        "action_source",
        "resolved_by_event",
        "event_type",
        "event_date",
        "event_source",
        "active_quarantine",
        "quarantine_until",
    ]
    if anomaly.empty:
        return pd.DataFrame(columns=columns), []

    confirmed = corporate_actions[corporate_actions["status"].eq("confirmed")].copy()
    confirmed_events = (
        verified_events[verified_events["status"].eq("confirmed")].copy()
        if verified_events is not None and not verified_events.empty
        else _empty_events()
    )
    max_data_date = pd.Timestamp(work["date"].max()).normalize()
    records: list[dict[str, Any]] = []
    for _, row in anomaly.iterrows():
        anomaly_date = pd.Timestamp(row["date"]).normalize()
        ticker_actions = confirmed[confirmed["ticker"].eq(str(row["ticker"]))].copy()
        if not ticker_actions.empty:
            ticker_actions["distance_days"] = (
                ticker_actions["effective_date"] - anomaly_date
            ).abs().dt.days
            ticker_actions = ticker_actions[ticker_actions["distance_days"].le(3)]
        matched = (
            ticker_actions.sort_values("distance_days").head(1)
            if "distance_days" in ticker_actions.columns
            else ticker_actions.head(0)
        )
        action_resolved = not matched.empty
        ticker_events = confirmed_events
        if not confirmed_events.empty:
            ticker_events = confirmed_events[
                confirmed_events["ticker"].eq(str(row["ticker"]))
                & confirmed_events["event_date"].dt.normalize().eq(anomaly_date)
            ]
        matched_event = ticker_events.head(1)
        event_resolved = not matched_event.empty
        resolved = action_resolved or event_resolved
        active = (
            not resolved
            and anomaly_date <= max_data_date
            and (max_data_date - anomaly_date).days <= max(0, int(quarantine_days))
        )
        action = matched.iloc[0] if action_resolved else None
        event = matched_event.iloc[0] if event_resolved else None
        records.append(
            {
                "ticker": str(row["ticker"]),
                "date": anomaly_date.date().isoformat(),
                "prev_close": round(float(row["prev_close"]), 6),
                "close": round(float(row["close"]), 6),
                "change_pct": round(float(row["change_pct"]), 4),
                "resolved": bool(resolved),
                "resolved_by_action": bool(action_resolved),
                "action_type": str(action["action_type"]) if action is not None else "",
                "action_effective_date": (
                    pd.Timestamp(action["effective_date"]).date().isoformat()
                    if action is not None
                    else ""
                ),
                "action_source": str(action["source"]) if action is not None else "",
                "resolved_by_event": bool(event_resolved),
                "event_type": str(event["event_type"]) if event is not None else "",
                "event_date": (
                    pd.Timestamp(event["event_date"]).date().isoformat()
                    if event is not None
                    else ""
                ),
                "event_source": str(event["source"]) if event is not None else "",
                "active_quarantine": bool(active),
                "quarantine_until": (
                    (anomaly_date + timedelta(days=max(0, int(quarantine_days))))
                    .date()
                    .isoformat()
                    if active
                    else ""
                ),
            }
        )

    details = pd.DataFrame(records, columns=columns)
    quarantined = sorted(
        details.loc[details["active_quarantine"].eq(True), "ticker"].unique().tolist()
    )
    return details, quarantined


def reconcile_price_frames(
    primary: pd.DataFrame,
    reference: pd.DataFrame,
    lookback_sessions: int,
    max_close_diff_pct: float,
    max_mismatch_ratio: float,
) -> dict[str, Any]:
    for label, frame in [("primary", primary), ("reference", reference)]:
        missing = [column for column in ["date", "ticker", "close"] if column not in frame.columns]
        if missing:
            raise ValueError(f"{label} reconciliation frame is missing columns: {missing}")

    left = primary[["date", "ticker", "close"]].copy()
    right = reference[["date", "ticker", "close"]].copy()
    for frame in [left, right]:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame.dropna(subset=["date", "ticker", "close"], inplace=True)

    common_dates = sorted(set(left["date"].dt.normalize()) & set(right["date"].dt.normalize()))
    selected_dates = common_dates[-max(1, int(lookback_sessions)) :]
    left = left[left["date"].dt.normalize().isin(selected_dates)]
    right = right[right["date"].dt.normalize().isin(selected_dates)]
    merged = left.merge(
        right,
        on=["date", "ticker"],
        how="inner",
        suffixes=("_primary", "_reference"),
    )
    expected_rows = int(len(left.drop_duplicates(subset=["date", "ticker"])))
    if merged.empty or expected_rows == 0:
        return {
            "status": "unavailable",
            "pass": False,
            "message": "No overlapping primary/reference rows for reconciliation",
            "rows_compared": 0,
            "coverage_ratio": 0.0,
            "mismatch_rows": 0,
            "mismatch_ratio": 0.0,
            "max_close_diff_pct": None,
        }

    denominator = merged["close_reference"].abs().replace(0, pd.NA)
    merged["close_diff_pct"] = (
        (merged["close_primary"] - merged["close_reference"]).abs() / denominator * 100.0
    )
    merged["mismatch"] = merged["close_diff_pct"].gt(float(max_close_diff_pct))
    mismatch_rows = int(merged["mismatch"].sum())
    mismatch_ratio = float(mismatch_rows / len(merged))
    coverage_ratio = float(len(merged) / expected_rows)
    passed = bool(coverage_ratio >= 0.95 and mismatch_ratio <= float(max_mismatch_ratio))
    return {
        "status": "pass" if passed else "failed",
        "pass": passed,
        "message": (
            "Independent price reconciliation passed"
            if passed
            else "Independent price reconciliation exceeded tolerance"
        ),
        "rows_compared": int(len(merged)),
        "coverage_ratio": round(coverage_ratio, 6),
        "mismatch_rows": mismatch_rows,
        "mismatch_ratio": round(mismatch_ratio, 6),
        "max_close_diff_pct": round(float(merged["close_diff_pct"].max()), 6),
        "threshold_close_diff_pct": float(max_close_diff_pct),
        "threshold_mismatch_ratio": float(max_mismatch_ratio),
    }


def run_price_quality_audit(
    prices: pd.DataFrame,
    config: PriceQualitySettings,
    reconciliation_primary: pd.DataFrame | None = None,
    reconciliation_reference: pd.DataFrame | None = None,
    primary_source: str = "",
    reference_source: str = "",
    reconciliation_unavailable_reason: str = "",
) -> dict[str, Any]:
    actions = load_corporate_actions(config.corporate_actions_path)
    verified_events = load_verified_price_events(config.verified_price_events_path)
    adjusted = build_split_adjusted_prices(prices, actions)
    adjusted_path = Path(config.adjusted_prices_path)
    adjusted_path.parent.mkdir(parents=True, exist_ok=True)
    adjusted.to_csv(adjusted_path, index=False)

    anomalies, quarantined = classify_price_anomalies(
        prices=prices,
        corporate_actions=actions,
        threshold_pct=float(config.outlier_threshold_pct),
        quarantine_days=int(config.quarantine_days),
        verified_events=verified_events,
    )
    anomaly_path = Path(config.anomaly_report_path)
    anomaly_path.parent.mkdir(parents=True, exist_ok=True)
    anomalies.to_csv(anomaly_path, index=False)

    if not bool(config.reconciliation_enabled):
        reconciliation = {
            "status": "disabled",
            "pass": True,
            "message": "Independent price reconciliation disabled",
        }
    elif reconciliation_primary is None or reconciliation_reference is None:
        reconciliation = {
            "status": "unavailable",
            "pass": not bool(config.reconciliation_required),
            "message": (
                str(reconciliation_unavailable_reason).strip()
                or "Independent reconciliation source is not configured or unavailable"
            ),
            "rows_compared": 0,
        }
    else:
        reconciliation = reconcile_price_frames(
            primary=reconciliation_primary,
            reference=reconciliation_reference,
            lookback_sessions=int(config.reconciliation_lookback_sessions),
            max_close_diff_pct=float(config.reconciliation_max_close_diff_pct),
            max_mismatch_ratio=float(config.reconciliation_max_mismatch_ratio),
        )
        if reconciliation["status"] == "unavailable" and not bool(config.reconciliation_required):
            reconciliation["pass"] = True
    reconciliation["required"] = bool(config.reconciliation_required)
    reconciliation["primary_source"] = str(primary_source)
    reconciliation["reference_source"] = str(reference_source)

    reconciliation_path = Path(config.reconciliation_report_path)
    reconciliation_path.parent.mkdir(parents=True, exist_ok=True)
    reconciliation_path.write_text(
        json.dumps(reconciliation, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    unresolved = (
        anomalies["resolved"].eq(False)
        if "resolved" in anomalies.columns
        else pd.Series(dtype=bool)
    )
    return {
        "adjusted_prices_path": str(adjusted_path),
        "corporate_actions_path": str(config.corporate_actions_path),
        "corporate_actions_count": int(len(actions)),
        "verified_price_events_path": str(config.verified_price_events_path),
        "verified_price_events_count": int(len(verified_events)),
        "anomaly_report_path": str(anomaly_path),
        "anomaly_count": int(len(anomalies)),
        "unresolved_anomaly_count": int(unresolved.sum()) if len(unresolved) else 0,
        "active_unresolved_count": int(len(quarantined)),
        "quarantined_tickers": quarantined,
        "block_on_active_unresolved_action": bool(config.block_on_active_unresolved_action),
        "reconciliation": reconciliation,
    }
