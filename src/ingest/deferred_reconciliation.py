from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import Settings
from src.ingest.providers.rest_provider import RestEodProvider
from src.ingest.quality import reconcile_price_frames_with_details
from src.ingest.reconciliation_readiness import probe_eod_provider_account
from src.ingest.validator import validate_prices


TickerFetcher = Callable[[str, str, str], pd.DataFrame]
_SCHEMA_VERSION = 2
_SECRET_QUERY = re.compile(
    r"([?&](?:api_token|token|api_key|apikey)=)[^&\s]+",
    flags=re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error(exc: Exception) -> str:
    detail = _SECRET_QUERY.sub(r"\1***", str(exc).strip())
    return f"{exc.__class__.__name__}: {detail}" if detail else exc.__class__.__name__


def _rollout_progress(
    *,
    state: dict[str, Any],
    cycle: int,
    completed_tickers: set[str],
    universe_size: int,
    batch_size: int,
    cycle_completed: bool,
) -> dict[str, Any]:
    successful_dates = {
        str(row.get("run_date", "")).strip()
        for row in state.get("runs", [])
        if isinstance(row, dict)
        and int(row.get("cycle", 0) or 0) == cycle
        and (
            bool(row.get("success_tickers"))
            or (
                bool(row.get("idempotent_skip"))
                and int(row.get("completed_current_cycle", 0) or 0) > 0
            )
        )
        and str(row.get("run_date", "")).strip()
    }
    last_successful = state.get("last_successful_batch", {})
    if (
        isinstance(last_successful, dict)
        and int(last_successful.get("cycle", 0) or 0) == cycle
        and int(last_successful.get("completed_current_cycle", 0) or 0) > 0
    ):
        last_date = str(last_successful.get("run_date", "")).strip()
        if last_date:
            successful_dates.add(last_date)

    minimum_dates = (
        int(math.ceil(universe_size / batch_size))
        if universe_size > 0 and batch_size > 0
        else 0
    )
    completed_count = min(len(completed_tickers), universe_size)
    successful_date_count = len(successful_dates)
    complete = bool(
        cycle_completed
        and universe_size > 0
        and completed_count >= universe_size
        and successful_date_count >= minimum_dates
    )
    return {
        "cycle": cycle,
        "status": "complete" if complete else "collecting",
        "successful_dates": sorted(successful_dates),
        "successful_date_count": successful_date_count,
        "minimum_successful_dates_required": minimum_dates,
        "remaining_successful_dates": max(minimum_dates - successful_date_count, 0),
        "completed_tickers": completed_count,
        "universe_tickers": universe_size,
        "remaining_tickers": max(universe_size - completed_count, 0),
        "ticker_progress_ratio": round(
            completed_count / universe_size if universe_size else 0.0,
            6,
        ),
        "cycle_completed": cycle_completed,
        "ready_for_deferred_audit": complete,
        "same_day_reconciliation": False,
        "final_execution_eligible": False,
    }


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)
    return payload if isinstance(payload, dict) else dict(default)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_universe(path: str | Path) -> list[str]:
    universe_path = Path(path)
    if not universe_path.exists():
        return []
    frame = pd.read_csv(universe_path)
    if "ticker" not in frame.columns:
        return []
    return sorted(
        {
            str(value).strip().upper()
            for value in frame["ticker"].tolist()
            if str(value).strip()
        }
    )


def _load_canonical(path: str | Path, source: str) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        return pd.DataFrame()
    raw = pd.read_csv(target)
    canonical, _ = validate_prices(
        raw,
        source=source,
        max_staleness_days=10000,
    )
    return canonical


def _merge_cache(
    *,
    path: Path,
    incoming: pd.DataFrame,
    universe: list[str],
    retention_days: int,
    as_of_date: str,
) -> pd.DataFrame:
    existing = _load_canonical(path, source="eodhd_deferred")
    frames = [frame for frame in [existing, incoming] if not frame.empty]
    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged["ticker"] = merged["ticker"].astype(str).str.strip().str.upper()
    merged = merged.dropna(subset=["date"])
    merged = merged[merged["ticker"].isin(universe)]
    cutoff = pd.Timestamp(as_of_date) - pd.Timedelta(days=max(1, int(retention_days)))
    merged = merged[merged["date"].ge(cutoff)]
    merged = merged.sort_values(["ticker", "date", "ingested_at"])
    merged = merged.drop_duplicates(subset=["ticker", "date"], keep="last")
    merged = merged.reset_index(drop=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path, index=False)
    return merged


def _default_fetcher(settings: Settings) -> TickerFetcher:
    provider = RestEodProvider(settings.data.provider.rest)

    def fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        return provider.fetch_daily(
            start_date=start_date,
            end_date=end_date,
            tickers=[ticker],
        )

    return fetch


def _audit_cache(
    *,
    settings: Settings,
    universe: list[str],
    cache: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame]:
    cfg = settings.data.price_quality
    deferred = cfg.deferred_eod_reconciliation
    details_columns = [
        "date",
        "ticker",
        "close_primary",
        "close_reference",
        "matched",
        "close_diff_pct",
        "mismatch",
    ]
    empty_details = pd.DataFrame(columns=details_columns)
    primary = _load_canonical(
        settings.data.canonical_prices_path,
        source="yfinance_primary",
    )
    if primary.empty:
        return (
            {
                "status": "unavailable",
                "message": "Canonical daily prices are unavailable",
                "research_evidence_eligible": False,
            },
            empty_details,
        )
    if cache.empty:
        return (
            {
                "status": "collecting",
                "message": "Deferred EODHD cache has no validated rows yet",
                "research_evidence_eligible": False,
            },
            empty_details,
        )

    primary = primary[primary["ticker"].isin(universe)].copy()
    reference = cache[cache["ticker"].isin(universe)].copy()
    minimum_tickers = max(
        1,
        int(math.ceil(len(universe) * float(cfg.reconciliation_min_coverage_ratio))),
    )
    primary_counts = (
        primary.groupby(primary["date"].dt.strftime("%Y-%m-%d"))["ticker"]
        .nunique()
        .to_dict()
    )
    reference_counts = (
        reference.groupby(reference["date"].dt.strftime("%Y-%m-%d"))["ticker"]
        .nunique()
        .to_dict()
    )
    fully_covered_dates = sorted(
        date_text
        for date_text, reference_count in reference_counts.items()
        if int(reference_count) >= minimum_tickers
        and int(primary_counts.get(date_text, 0)) >= minimum_tickers
    )
    cache_tickers = int(reference["ticker"].nunique()) if not reference.empty else 0
    cache_coverage = float(cache_tickers / len(universe)) if universe else 0.0
    base = {
        "minimum_tickers_per_session": minimum_tickers,
        "universe_tickers": len(universe),
        "cache_tickers": cache_tickers,
        "cache_ticker_coverage_ratio": round(cache_coverage, 6),
        "fully_covered_session_count": len(fully_covered_dates),
        "fully_covered_session_dates": fully_covered_dates[
            -max(1, int(cfg.reconciliation_lookback_sessions)) :
        ],
    }
    required_sessions = max(1, int(cfg.reconciliation_lookback_sessions))
    if len(fully_covered_dates) < required_sessions:
        return (
            {
                **base,
                "status": "collecting",
                "message": (
                    "Deferred reference is collecting full-universe history; "
                    f"{len(fully_covered_dates)}/{required_sessions} required sessions ready"
                ),
                "research_evidence_eligible": False,
            },
            empty_details,
        )

    selected_dates = fully_covered_dates[-required_sessions:]
    all_primary_dates = sorted(
        primary["date"].dt.strftime("%Y-%m-%d").dropna().unique().tolist()
    )
    primary = primary[
        primary["date"].dt.strftime("%Y-%m-%d").isin(selected_dates)
    ].copy()
    reference = reference[
        reference["date"].dt.strftime("%Y-%m-%d").isin(selected_dates)
    ].copy()
    summary, details = reconcile_price_frames_with_details(
        primary=primary,
        reference=reference,
        lookback_sessions=required_sessions,
        max_close_diff_pct=float(cfg.reconciliation_max_close_diff_pct),
        max_mismatch_ratio=float(cfg.reconciliation_max_mismatch_ratio),
        min_coverage_ratio=float(cfg.reconciliation_min_coverage_ratio),
    )
    latest_reconciled = str(summary.get("market_date", ""))
    lag_sessions = len(
        [value for value in all_primary_dates if value > latest_reconciled]
    )
    passed = bool(summary.get("pass", False))
    return (
        {
            **base,
            **summary,
            "status": "pass" if passed else "failed",
            "research_evidence_eligible": passed,
            "lag_sessions": lag_sessions,
        },
        details,
    )


def collect_deferred_eod_reconciliation(
    settings: Settings,
    *,
    now: datetime | None = None,
    fetcher: TickerFetcher | None = None,
    account_fetcher: Callable[[str, int], object] | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Collect one free-tier EOD batch and build delayed research-only evidence."""
    cfg = settings.data.price_quality
    deferred = cfg.deferred_eod_reconciliation
    if not bool(deferred.enabled):
        return {
            "status": "disabled",
            "mode": "deferred_free_tier",
            "final_execution_eligible": False,
            "message": "Deferred EOD reconciliation is disabled",
        }

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(ZoneInfo(settings.data.timezone))
    run_date = local_now.date().isoformat()
    generated_at = current.astimezone(timezone.utc).isoformat()

    universe = _load_universe(settings.data.universe_csv_path)
    state_path = Path(deferred.state_path)
    cache_path = Path(deferred.cache_path)
    report_path = Path(deferred.report_path)
    details_path = Path(deferred.details_path)
    default_state: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "cycle": 1,
        "completed_cycle_tickers": [],
        "last_success_date": "",
        "last_cycle_completed_at": "",
        "runs": [],
    }
    state = _read_json(state_path, default_state)
    state["schema_version"] = _SCHEMA_VERSION
    collection_cycle = int(state.get("cycle", 1) or 1)
    completed = {
        str(value).strip().upper()
        for value in state.get("completed_cycle_tickers", [])
        if str(value).strip().upper() in set(universe)
    }
    last_successful_batch = state.get("last_successful_batch")
    last_success_date = str(state.get("last_success_date", "")).strip()
    if not isinstance(last_successful_batch, dict) or not last_successful_batch:
        if last_success_date:
            last_completed_cycle = int(state.get("last_completed_cycle", 0) or 0)
            recovered_completed = set(completed)
            recovered_cycle = collection_cycle
            recovered_cycle_completed = False
            if last_completed_cycle > 0 and not recovered_completed:
                recovered_cycle = last_completed_cycle
                recovered_completed = set(universe)
                recovered_cycle_completed = True
            state["last_successful_batch"] = {
                "run_date": last_success_date,
                "generated_at": "",
                "cycle": recovered_cycle,
                "success_tickers": [],
                "completed_cycle_tickers": sorted(recovered_completed),
                "completed_current_cycle": len(recovered_completed),
                "cycle_completed": recovered_cycle_completed,
                "reconstructed_from_state": True,
            }
    batch_size = max(1, min(int(deferred.batch_size), len(universe) or 1))
    pending = [ticker for ticker in universe if ticker not in completed]
    if not pending and universe:
        completed = set()
        pending = list(universe)
        collection_cycle += 1
        state["cycle"] = collection_cycle
    planned_batch = pending[:batch_size]

    account: dict[str, Any] = {
        "status": "not_checked",
        "ready": False,
        "required_calls": 0,
    }
    selected_batch: list[str] = []
    success_tickers: list[str] = []
    failures: list[dict[str, str]] = []
    skipped_same_day = str(state.get("last_success_date", "")) == run_date
    start_date = (
        local_now.date() - timedelta(days=max(1, int(deferred.lookback_calendar_days)))
    ).isoformat()
    end_date = run_date
    incoming_frames: list[pd.DataFrame] = []

    if skipped_same_day:
        account = {
            "status": "not_checked_idempotent_skip",
            "ready": True,
            "required_calls": 0,
        }
    elif not universe:
        failures.append(
            {
                "ticker": "",
                "error": "Active universe is missing or invalid",
            }
        )
    else:
        account = probe_eod_provider_account(
            settings,
            environ=environ,
            fetcher=account_fetcher,
            required_ticker_calls_override=len(planned_batch),
            now=current,
        )
        if bool(account.get("ready", False)):
            selected_batch = list(planned_batch)
            active_fetcher = fetcher or _default_fetcher(settings)
            for ticker in selected_batch:
                try:
                    raw = active_fetcher(ticker, start_date, end_date)
                    canonical, _ = validate_prices(
                        raw,
                        source="eodhd_deferred",
                        max_staleness_days=10000,
                    )
                    canonical = canonical[canonical["ticker"].eq(ticker)].copy()
                    if canonical.empty:
                        raise ValueError("Provider returned no canonical rows")
                    incoming_frames.append(canonical)
                    success_tickers.append(ticker)
                except Exception as exc:
                    error = _safe_error(exc)
                    failures.append({"ticker": ticker, "error": error})
                    if any(
                        marker in error
                        for marker in [
                            "HTTP Error 401",
                            "HTTP Error 402",
                            "HTTP Error 429",
                        ]
                    ):
                        break

    incoming = (
        pd.concat(incoming_frames, ignore_index=True, sort=False)
        if incoming_frames
        else pd.DataFrame()
    )
    cache = _merge_cache(
        path=cache_path,
        incoming=incoming,
        universe=universe,
        retention_days=int(deferred.cache_retention_calendar_days),
        as_of_date=run_date,
    )

    cycle_completed = False
    completed_for_report = set(completed)
    if success_tickers:
        completed.update(success_tickers)
        completed_for_report = set(completed)
        state["last_success_date"] = run_date
        if len(completed) >= len(universe):
            cycle_completed = True
            state["last_cycle_completed_at"] = generated_at
            state["last_completed_cycle"] = collection_cycle
            state["completed_cycle_tickers"] = []
            state["cycle"] = collection_cycle + 1
        else:
            state["completed_cycle_tickers"] = sorted(completed)
        state["last_successful_batch"] = {
            "run_date": run_date,
            "generated_at": generated_at,
            "cycle": collection_cycle,
            "success_tickers": success_tickers,
            "completed_cycle_tickers": sorted(completed_for_report),
            "completed_current_cycle": len(completed_for_report),
            "cycle_completed": cycle_completed,
            "reconstructed_from_state": False,
        }
    else:
        state["completed_cycle_tickers"] = sorted(completed)
    state["updated_at"] = generated_at
    run_record = {
        "run_date": run_date,
        "generated_at": generated_at,
        "cycle": collection_cycle,
        "selected_tickers": selected_batch,
        "success_tickers": success_tickers,
        "failures": failures,
        "idempotent_skip": skipped_same_day,
        "completed_current_cycle": len(completed_for_report),
        "cycle_completed": cycle_completed,
    }
    previous_runs = [
        row
        for row in state.get("runs", [])
        if isinstance(row, dict)
    ]
    state["runs"] = (previous_runs + [run_record])[-30:]
    rollout = _rollout_progress(
        state=state,
        cycle=collection_cycle,
        completed_tickers=completed_for_report,
        universe_size=len(universe),
        batch_size=batch_size,
        cycle_completed=cycle_completed,
    )
    state["rollout"] = rollout
    if cycle_completed:
        state["last_completed_rollout"] = rollout
    _write_json(state_path, state)

    audit, details = _audit_cache(
        settings=settings,
        universe=universe,
        cache=cache,
    )
    details_path.parent.mkdir(parents=True, exist_ok=True)
    details.to_csv(details_path, index=False)
    cache_digest = hashlib.sha256(cache_path.read_bytes()).hexdigest() if cache_path.exists() else ""
    status = str(audit.get("status", "collecting"))
    if not skipped_same_day and universe and not bool(account.get("ready", False)):
        status = "blocked"
    elif failures and not success_tickers:
        status = "blocked"
    elif failures:
        status = "collecting"

    payload = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at": generated_at,
        "run_date": run_date,
        "status": status,
        "mode": "deferred_free_tier",
        "same_day_reconciliation": False,
        "final_execution_eligible": False,
        "research_evidence_eligible": bool(
            audit.get("research_evidence_eligible", False)
        ),
        "sources": {
            "daily_primary": "yfinance_primary",
            "deferred_reference": "eodhd_deferred",
        },
        "batch": {
            "cycle": collection_cycle,
            "next_cycle": int(state.get("cycle", collection_cycle) or collection_cycle),
            "cycle_completed": cycle_completed,
            "batch_size": batch_size,
            "planned_tickers": planned_batch,
            "selected_tickers": selected_batch,
            "success_tickers": success_tickers,
            "failures": failures,
            "idempotent_skip": skipped_same_day,
            "completed_current_cycle": len(completed_for_report),
            "universe_tickers": len(universe),
            "start_date": start_date,
            "end_date": end_date,
        },
        "rollout": rollout,
        "last_successful_batch": state.get("last_successful_batch", {}),
        "account": account,
        "audit": audit,
        "artifacts": {
            "cache_path": str(cache_path),
            "cache_sha256": cache_digest,
            "state_path": str(state_path),
            "details_path": str(details_path),
        },
        "message": (
            "Deferred reconciliation passed for research evidence; it is not same-day execution evidence"
            if status == "pass"
            else "Deferred reconciliation is collecting or blocked; final execution remains disabled"
        ),
    }
    if skipped_same_day:
        persisted_report = _read_json(report_path, {})
        if persisted_report:
            persisted_rollout = rollout
            last_completed_rollout = state.get("last_completed_rollout", {})
            last_successful = state.get("last_successful_batch", {})
            if (
                isinstance(last_completed_rollout, dict)
                and last_completed_rollout
                and isinstance(last_successful, dict)
                and bool(last_successful.get("cycle_completed", False))
            ):
                persisted_rollout = last_completed_rollout
            persisted_report["schema_version"] = _SCHEMA_VERSION
            persisted_report["rollout"] = persisted_rollout
            persisted_report["last_successful_batch"] = state.get(
                "last_successful_batch",
                {},
            )
            persisted_report["last_checked_at"] = generated_at
            _write_json(report_path, persisted_report)
    else:
        _write_json(report_path, payload)
    return payload
