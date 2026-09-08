from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib import error, request
from urllib.parse import urlparse

IDX_HOSTS = {"idx.co.id", "www.idx.co.id"}
REQUIRED = {"announcement_id", "expected_source_url", "verification_status"}

def _load_candidates(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise ValueError("candidate plan must contain candidates")
    seen = set()
    for row in rows:
        missing = [key for key in REQUIRED if not str(row.get(key, "")).strip()]
        identity = str(row.get("announcement_id", "")).strip()
        parsed = urlparse(str(row.get("expected_source_url", "")))
        if missing or identity in seen or parsed.scheme != "https" or parsed.hostname not in IDX_HOSTS:
            raise ValueError(f"invalid official IDX candidate: {identity}")
        if row["verification_status"] != "unverified_research_candidate":
            raise ValueError(f"candidate must remain unverified: {identity}")
        seen.add(identity)
    return rows

def _active_ids(path: Path):
    if not path.exists():
        return set()
    documents = json.loads(path.read_text(encoding="utf-8")).get("documents", [])
    return {str(row.get("announcement_id", "")).strip() for row in documents}
ProbeHead = Callable[[str, int], tuple[int, str, Mapping[str, str], float]]


class _NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def _default_probe_head(url: str, timeout_seconds: int) -> tuple[int, str, Mapping[str, str], float]:
    started = time.perf_counter()
    req = request.Request(
        url=url,
        method="HEAD",
        headers={
            "Accept": "application/zip, application/octet-stream;q=0.9, */*;q=0.1",
            "User-Agent": "idx-trading-lab-source-monitor/1.0",
        },
    )
    opener = request.build_opener(_NoRedirectHandler)
    try:
        with opener.open(req, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200))
            final_url = str(response.geturl())
            headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    except error.HTTPError as exc:
        status = int(exc.code)
        final_url = str(exc.geturl() or url)
        headers = {str(key).lower(): str(value) for key, value in (exc.headers or {}).items()}
    except error.URLError as exc:
        raise RuntimeError(f"network_error: {exc.reason}") from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    return status, final_url, headers, elapsed_ms


def _zip_response_hint(headers: Mapping[str, str]) -> bool:
    content_type = str(headers.get("content-type", "")).lower()
    disposition = str(headers.get("content-disposition", "")).lower()
    return "zip" in content_type or "octet-stream" in content_type or ".zip" in disposition

def audit_idx_membership_acquisition(
    candidate_plan_path: str = "data/reference/index_membership_sources/idx_acquisition_candidates.json",
    active_manifest_path: str = "data/reference/index_membership_sources/idx_manifest.json",
    archive_dir: str = "data/reference/index_membership_sources/idx",
    output_json: str = "reports/idx_membership_archive_acquisition_audit.json",
    expected_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Audit research candidates without downloading files or mutating the active manifest."""
    candidates = _load_candidates(Path(candidate_plan_path))
    active_ids = _active_ids(Path(active_manifest_path))
    archives = Path(archive_dir)
    counts = expected_counts or DEFAULT_COUNTS

    records = []
    for candidate in candidates:
        announcement_id = str(candidate["announcement_id"]).strip()
        inspection = _inspect_archive(archives / str(candidate["archive_file"]), candidate, counts)
        already_active = announcement_id in active_ids
        ready = bool(
            inspection["archive_valid"]
            and inspection["period_matches_candidate"]
            and not already_active
        )
        if already_active:
            status = "already_in_active_manifest"
        elif ready:
            status = "ready_for_human_hash_pinning_review"
        elif inspection["archive_exists"]:
            status = "blocked_archive_validation"
        else:
            status = "blocked_archive_missing"
        records.append(
            {
                **candidate,
                **inspection,
                "already_in_active_manifest": already_active,
                "ready_for_manifest_review": ready,
                "status": status,
            }
        )

    ready_count = sum(bool(record["ready_for_manifest_review"]) for record in records)
    missing_count = sum(record["status"] == "blocked_archive_missing" for record in records)
    invalid_count = sum(record["status"] == "blocked_archive_validation" for record in records)
    active_count = sum(record["status"] == "already_in_active_manifest" for record in records)
    if missing_count:
        status = "blocked_missing_official_archives"
        next_action = "Acquire the listed missing official IDX/TICMI ZIP archives through an authorized browser or supplied official documents."
    elif invalid_count:
        status = "blocked_invalid_official_archives"
        next_action = "Replace or correct invalid local archives, then rerun this audit before human review."
    elif ready_count:
        status = "candidates_ready_for_human_review"
        next_action = "Have a human verify each ready local ZIP, then hash-pin it in the active manifest and rerun stage-membership-history."
    else:
        status = "all_candidates_in_active_manifest"
        next_action = "Rerun stage-membership-history and all downstream data gates; execution remains disabled."
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_state": "EXECUTION_DISABLED",
        "status": status,
        "candidate_plan": str(candidate_plan_path),
        "active_manifest": str(active_manifest_path),
        "archive_dir": str(archive_dir),
        "candidate_count": len(records),
        "missing_archive_count": missing_count,
        "invalid_archive_count": invalid_count,
        "already_active_count": active_count,
        "ready_for_manifest_review_count": ready_count,
        "automatic_download_performed": False,
        "automatic_manifest_write_performed": False,
        "records": records,
        "point_in_time_model_ready": False,
        "final_decision_eligible": False,
        "next_action": next_action,
    }
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return payload


def probe_idx_membership_source_availability(
    candidate_plan_path: str = "data/reference/index_membership_sources/idx_acquisition_candidates.json",
    active_manifest_path: str = "data/reference/index_membership_sources/idx_manifest.json",
    output_json: str = "reports/idx_membership_source_availability.json",
    timeout_seconds: int = 15,
    probe_head: ProbeHead | None = None,
) -> dict[str, Any]:
    """Probe official candidate URLs with HEAD only; never download or mutate data."""
    if not 1 <= int(timeout_seconds) <= 60:
        raise ValueError("timeout_seconds must be between 1 and 60")
    candidates = _load_candidates(Path(candidate_plan_path))
    active_ids = _active_ids(Path(active_manifest_path))
    fetch = probe_head or _default_probe_head
    records = []
    for candidate in candidates:
        announcement_id = str(candidate["announcement_id"]).strip()
        if announcement_id in active_ids:
            records.append(
                {
                    "announcement_id": announcement_id,
                    "source_url": str(candidate["expected_source_url"]),
                    "status": "already_in_active_manifest",
                    "http_status": None,
                    "available_for_manual_download": False,
                    "probe_performed": False,
                }
            )
            continue
        source_url = str(candidate["expected_source_url"])
        record: dict[str, Any] = {
            "announcement_id": announcement_id,
            "source_url": source_url,
            "status": "probe_error",
            "http_status": None,
            "available_for_manual_download": False,
            "probe_performed": True,
        }
        try:
            http_status, final_url, headers, elapsed_ms = fetch(source_url, int(timeout_seconds))
            final = urlparse(final_url)
            official_final_url = final.scheme == "https" and final.hostname in IDX_HOSTS
            normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
            zip_hint = _zip_response_hint(normalized_headers)
            available = 200 <= int(http_status) < 300 and official_final_url and zip_hint
            if not official_final_url:
                probe_status = "blocked_untrusted_redirect"
            elif int(http_status) in {401, 403}:
                probe_status = "blocked_access_control"
            elif int(http_status) == 404:
                probe_status = "not_found"
            elif int(http_status) == 405:
                probe_status = "head_not_supported"
            elif available:
                probe_status = "available_for_manual_download"
            else:
                probe_status = "unavailable_http_response"
            record.update(
                {
                    "status": probe_status,
                    "http_status": int(http_status),
                    "final_url": final_url,
                    "official_final_url": official_final_url,
                    "zip_response_hint": zip_hint,
                    "content_type": str(normalized_headers.get("content-type", "")),
                    "content_length": str(normalized_headers.get("content-length", "")),
                    "elapsed_ms": float(elapsed_ms),
                    "available_for_manual_download": available,
                }
            )
        except (OSError, RuntimeError, ValueError) as exc:
            record["error"] = str(exc)[:300]
        records.append(record)

    pending = [record for record in records if record["status"] != "already_in_active_manifest"]
    available_count = sum(bool(record["available_for_manual_download"]) for record in pending)
    if not pending:
        status = "all_candidates_in_active_manifest"
        next_action = "Rerun membership staging and every downstream gate; execution remains disabled."
    elif available_count == len(pending):
        status = "sources_available_for_manual_download"
        next_action = "A human must download and review each official ZIP before manifest promotion."
    elif available_count:
        status = "blocked_partial_source_availability"
        next_action = "Manually review available official sources and continue the IDX/TICMI request for missing archives."
    else:
        status = "blocked_sources_unavailable"
        next_action = "Keep the IDX/TICMI human request open; this monitor will probe again on its next schedule."
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_state": "EXECUTION_DISABLED",
        "status": status,
        "probe_method": "HEAD",
        "candidate_count": len(candidates),
        "pending_source_count": len(pending),
        "available_for_manual_download_count": available_count,
        "records": records,
        "network_request_performed": bool(pending),
        "response_body_bytes_read": 0,
        "automatic_download_performed": False,
        "active_manifest_write_performed": False,
        "canonical_membership_written": False,
        "human_review_required": True,
        "point_in_time_model_ready": False,
        "final_decision_eligible": False,
        "next_action": next_action,
    }
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return payload
