from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Callable, Mapping
from urllib import parse, request
from urllib.error import HTTPError

from src.config import Settings
from src.ingest.providers.rest_provider import inspect_rest_provider_environment


AccountFetcher = Callable[[str, int], object]


def _universe_ticker_count(path: str | Path) -> int:
    universe_path = Path(path)
    if not universe_path.exists():
        return 0
    with universe_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        tickers = {
            str(row.get("ticker", "")).strip().upper()
            for row in rows
            if str(row.get("ticker", "")).strip()
        }
    return len(tickers)


def _fetch_account_payload(url: str, timeout_seconds: int) -> object:
    req = request.Request(url=url, headers={"Accept": "application/json"})
    with request.urlopen(req, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def probe_eod_provider_account(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    fetcher: AccountFetcher | None = None,
    required_ticker_calls_override: int | None = None,
) -> dict[str, object]:
    """Check provider quota without returning account identity or credential values."""
    quality = settings.data.price_quality
    if not bool(quality.provider_account_probe_enabled):
        return {
            "status": "disabled",
            "ready": True,
            "message": "Provider account probe is disabled",
        }

    token_env = str(quality.provider_account_token_env).strip()
    active_env = os.environ if environ is None else environ
    token = str(active_env.get(token_env, "")).strip()
    if not token:
        return {
            "status": "blocked",
            "ready": False,
            "reason_codes": ["provider_account_token_missing"],
            "missing_environment_variables": [token_env] if token_env else [],
            "message": "Provider account probe blocked by a missing environment variable",
        }

    status_url = str(quality.provider_account_status_url).strip()
    if not status_url.lower().startswith("https://"):
        return {
            "status": "blocked",
            "ready": False,
            "reason_codes": ["provider_account_status_url_invalid"],
            "message": "Provider account probe requires an HTTPS status URL",
        }

    ticker_count = _universe_ticker_count(settings.data.universe_csv_path)
    deferred = quality.deferred_eod_reconciliation
    if required_ticker_calls_override is not None:
        planned_tickers = max(0, int(required_ticker_calls_override))
        quota_scope = "explicit_batch"
    elif bool(deferred.enabled):
        planned_tickers = min(
            ticker_count,
            max(1, int(deferred.batch_size)),
        )
        quota_scope = "deferred_batch"
    else:
        planned_tickers = ticker_count
        quota_scope = "full_universe"
    cost_per_ticker = max(1, int(quality.provider_account_call_cost_per_ticker))
    reserve = max(0, int(quality.provider_account_minimum_reserve_calls))
    required_calls = planned_tickers * cost_per_ticker + reserve
    if ticker_count <= 0:
        return {
            "status": "blocked",
            "ready": False,
            "reason_codes": ["provider_account_universe_unavailable"],
            "required_calls": required_calls,
            "planned_tickers": planned_tickers,
            "quota_scope": quota_scope,
            "message": "Provider account probe could not determine the active universe",
        }

    url = status_url + "?" + parse.urlencode({"api_token": token, "fmt": "json"})
    active_fetcher = fetcher or _fetch_account_payload
    try:
        payload = active_fetcher(url, int(settings.data.provider.rest.timeout_seconds))
    except HTTPError as exc:
        return {
            "status": "blocked",
            "ready": False,
            "reason_codes": ["provider_account_http_error"],
            "http_status": int(exc.code),
            "required_calls": required_calls,
            "message": "Provider account status request failed",
        }
    except Exception as exc:
        return {
            "status": "blocked",
            "ready": False,
            "reason_codes": ["provider_account_probe_failed"],
            "error_type": exc.__class__.__name__,
            "required_calls": required_calls,
            "message": "Provider account status request failed",
        }

    if not isinstance(payload, dict):
        return {
            "status": "blocked",
            "ready": False,
            "reason_codes": ["provider_account_payload_invalid"],
            "required_calls": required_calls,
            "message": "Provider account status payload is invalid",
        }

    daily_limit = max(0, _as_int(payload.get("dailyRateLimit")))
    used_calls = max(0, _as_int(payload.get("apiRequests")))
    extra_calls = max(0, _as_int(payload.get("extraLimit")))
    remaining_calls = max(daily_limit - used_calls, 0) + extra_calls
    reason_codes: list[str] = []
    if daily_limit < required_calls:
        reason_codes.append("provider_daily_limit_below_universe_requirement")
    if remaining_calls < required_calls:
        reason_codes.append("provider_remaining_quota_insufficient")
    ready = not reason_codes
    return {
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "reason_codes": reason_codes,
        "subscription_type": str(payload.get("subscriptionType", "")),
        "usage_date": str(payload.get("apiRequestsDate", "")),
        "daily_limit": daily_limit,
        "used_calls": used_calls,
        "extra_calls": extra_calls,
        "remaining_calls": remaining_calls,
        "universe_tickers": ticker_count,
        "planned_tickers": planned_tickers,
        "quota_scope": quota_scope,
        "call_cost_per_ticker": cost_per_ticker,
        "reserve_calls": reserve,
        "required_calls": required_calls,
        "message": (
            "Provider account quota is sufficient for the planned EOD request batch"
            if ready
            else "Provider account quota is insufficient for the planned EOD request batch"
        ),
    }


def assess_eod_reconciliation_readiness(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Validate production EOD reconciliation configuration without network access."""
    provider = settings.data.provider
    quality = settings.data.price_quality
    env_status = inspect_rest_provider_environment(
        provider.rest,
        environ=dict(environ) if environ is not None else None,
    )

    reference_path = str(quality.reconciliation_reference_csv_path).strip()
    reference_csv_ok = False
    reference_csv_reason = "not_configured"
    if reference_path:
        reference = Path(reference_path)
        canonical = Path(settings.data.canonical_prices_path)
        if not reference.exists():
            reference_csv_reason = "missing"
        elif reference.resolve() == canonical.resolve():
            reference_csv_reason = "same_as_canonical"
        else:
            reference_csv_ok = True
            reference_csv_reason = "configured"

    yfinance_reference_ok = bool(quality.reconciliation_yfinance_enabled)
    independent_reference_ok = bool(reference_csv_ok or yfinance_reference_ok)
    thresholds_ok = bool(
        0.0 < float(quality.reconciliation_min_coverage_ratio) <= 1.0
        and 0.0 <= float(quality.reconciliation_max_mismatch_ratio) <= 1.0
        and float(quality.reconciliation_max_close_diff_pct) >= 0.0
        and int(quality.reconciliation_min_consecutive_sessions) >= 5
    )
    market_calendar_available = Path(quality.reconciliation_market_calendar_path).is_file()
    evidence_paths_ok = bool(
        str(quality.reconciliation_details_path).strip()
        and str(quality.reconciliation_evidence_dir).strip()
        and str(quality.reconciliation_evidence_history_path).strip()
        and str(quality.reconciliation_market_calendar_path).strip()
    )
    account_probe_configured = bool(
        not quality.provider_account_probe_enabled
        or (
            str(quality.provider_account_status_url).strip().lower().startswith("https://")
            and str(quality.provider_account_token_env).strip()
            and int(quality.provider_account_call_cost_per_ticker) >= 1
        )
    )
    deferred = quality.deferred_eod_reconciliation
    deferred_configured = bool(
        not deferred.enabled
        or (
            deferred.use_yfinance_as_daily_primary
            and 0 < int(deferred.batch_size) <= _universe_ticker_count(
                settings.data.universe_csv_path
            )
            and int(deferred.lookback_calendar_days) >= 7
            and str(deferred.cache_path).strip()
            and str(deferred.state_path).strip()
            and str(deferred.report_path).strip()
            and str(deferred.details_path).strip()
        )
    )

    checks = {
        "provider_is_rest": str(provider.kind).strip().lower() == "rest",
        "provider_environment_ready": bool(env_status["ok"]),
        "provider_account_probe_configured": account_probe_configured,
        "deferred_reconciliation_configured": deferred_configured,
        "reconciliation_enabled": bool(quality.reconciliation_enabled),
        "independent_reference_configured": independent_reference_ok,
        "evidence_collection_enabled": bool(quality.reconciliation_evidence_enabled),
        "evidence_paths_configured": evidence_paths_ok,
        "market_calendar_available": market_calendar_available,
        "thresholds_valid": thresholds_ok,
    }
    ready = bool(all(checks.values()))
    return {
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "checks": checks,
        "required_environment_variables": list(env_status["required"]),
        "missing_environment_variables": list(env_status["missing"]),
        "reference": {
            "csv_status": reference_csv_reason,
            "yfinance_enabled": yfinance_reference_ok,
        },
        "evidence": {
            "minimum_consecutive_sessions": int(
                quality.reconciliation_min_consecutive_sessions
            ),
            "minimum_coverage_ratio": float(
                quality.reconciliation_min_coverage_ratio
            ),
            "maximum_mismatch_ratio": float(
                quality.reconciliation_max_mismatch_ratio
            ),
            "enforcement_enabled": bool(quality.reconciliation_required),
        },
        "message": (
            "EOD reconciliation preflight passed"
            if ready
            else "EOD reconciliation preflight blocked; inspect failed checks and missing environment names"
        ),
    }