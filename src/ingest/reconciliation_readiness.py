from __future__ import annotations

from pathlib import Path
from typing import Mapping

from src.config import Settings
from src.ingest.providers.rest_provider import inspect_rest_provider_environment


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

    checks = {
        "provider_is_rest": str(provider.kind).strip().lower() == "rest",
        "provider_environment_ready": bool(env_status["ok"]),
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