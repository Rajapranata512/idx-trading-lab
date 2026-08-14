from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings
from src.features.contract import (
    CANONICAL_PRICE_COLUMNS,
    FEATURE_CONTRACT_VERSION,
    FEATURE_OUTPUT_COLUMNS,
    validate_feature_columns,
)
from src.utils.io import atomic_write_text


MANIFEST_SCHEMA_VERSION = 2
_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_ARTIFACT_NAMES = frozenset(
    {
        "active_universe",
        "adjusted_prices",
        "canonical_prices",
        "corporate_actions",
        "deferred_reconciliation_cache",
        "deferred_reconciliation_details",
        "deferred_reconciliation_report",
        "features",
        "price_reconciliation_incidents",
        "universe_history",
        "verified_price_events",
    }
)


class ResearchManifestError(ValueError):
    pass


def _artifact_specs(settings: Settings) -> list[dict[str, str]]:
    quality = settings.data.price_quality
    deferred = quality.deferred_eod_reconciliation
    return [
        {
            "name": "active_universe",
            "role": "point_in_time_universe_current",
            "path": settings.data.universe_csv_path,
            "format": "csv",
        },
        {
            "name": "adjusted_prices",
            "role": "feature_price_input",
            "path": quality.adjusted_prices_path,
            "format": "csv",
        },
        {
            "name": "canonical_prices",
            "role": "raw_canonical_price_audit",
            "path": settings.data.canonical_prices_path,
            "format": "csv",
        },
        {
            "name": "corporate_actions",
            "role": "price_adjustment_events",
            "path": quality.corporate_actions_path,
            "format": "csv",
        },
        {
            "name": "deferred_reconciliation_cache",
            "role": "independent_delayed_price_reference",
            "path": deferred.cache_path,
            "format": "csv",
        },
        {
            "name": "deferred_reconciliation_details",
            "role": "independent_price_comparison_rows",
            "path": deferred.details_path,
            "format": "csv",
        },
        {
            "name": "deferred_reconciliation_report",
            "role": "independent_price_comparison_summary",
            "path": deferred.report_path,
            "format": "json",
        },
        {
            "name": "features",
            "role": "model_feature_matrix",
            "path": "data/processed/features.parquet",
            "format": "parquet",
        },
        {
            "name": "price_reconciliation_incidents",
            "role": "reconciliation_incident_disposition",
            "path": "data/reference/price_reconciliation_incidents.csv",
            "format": "csv",
        },
        {
            "name": "universe_history",
            "role": "point_in_time_universe_history",
            "path": settings.data.universe_auto_update.history_path,
            "format": "csv",
        },
        {
            "name": "verified_price_events",
            "role": "non_corporate_price_event_annotations",
            "path": quality.verified_price_events_path,
            "format": "csv",
        },
    ]


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_bytes(path: Path, artifact_format: str) -> tuple[bytes, str]:
    raw = path.read_bytes()
    if artifact_format in {"csv", "json"}:
        text = raw.decode("utf-8-sig")
        normalized = text.replace(chr(13) + chr(10), chr(10)).replace(
            chr(13),
            chr(10),
        )
        return normalized.encode("utf-8"), "normalized_utf8_lf"
    return raw, "binary_bytes"


def _artifact_fingerprint(path: Path, artifact_format: str) -> dict[str, Any]:
    content, hash_mode = _artifact_bytes(path, artifact_format)
    return {
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "hash_mode": hash_mode,
    }


def _resolve_path(root: Path, raw_path: str | Path) -> Path:
    candidate = Path(raw_path)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _portable_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ResearchManifestError(
            f"Artifact path must stay inside repository root: {path}"
        ) from exc


def _timestamp_text(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat()


def _tabular_metadata(frame: pd.DataFrame) -> dict[str, Any]:
    date_coverage: dict[str, dict[str, str]] = {}
    date_columns = [
        "date",
        "market_date",
        "effective_from",
        "effective_to",
        "effective_until",
        "effective_date",
        "event_date",
        "as_of",
        "imported_at",
        "ingested_at",
    ]
    for column in date_columns:
        if column not in frame.columns or frame.empty:
            continue
        parsed = pd.to_datetime(frame[column], errors="coerce", utc=True).dropna()
        if not parsed.empty:
            date_coverage[column] = {
                "min": _timestamp_text(parsed.min()),
                "max": _timestamp_text(parsed.max()),
            }

    ticker_coverage: dict[str, Any] = {}
    if "ticker" in frame.columns:
        tickers = frame["ticker"].dropna().astype(str).str.strip()
        ticker_coverage = {
            "column": "ticker",
            "unique_count": int(tickers[tickers.ne("")].nunique()),
        }

    return {
        "rows": int(len(frame)),
        "columns": [
            {"name": str(column), "dtype": str(frame[column].dtype)}
            for column in frame.columns
        ],
        "date_coverage": date_coverage,
        "ticker_coverage": ticker_coverage,
    }


def _inspect_artifact(
    root: Path,
    spec: dict[str, str],
) -> dict[str, Any]:
    path = _resolve_path(root, spec["path"])
    portable_path = _portable_path(root, path)
    if not path.is_file():
        raise ResearchManifestError(
            f"Required research artifact is missing: {portable_path}"
        )

    metadata: dict[str, Any] = {
        "name": spec["name"],
        "role": spec["role"],
        "path": portable_path,
        "format": spec["format"],
        "required": True,
        **_artifact_fingerprint(path, spec["format"]),
    }
    if spec["format"] == "csv":
        metadata.update(_tabular_metadata(pd.read_csv(path, low_memory=False)))
    elif spec["format"] == "parquet":
        frame = pd.read_parquet(path)
        if spec["name"] == "features":
            try:
                validate_feature_columns(frame.columns)
            except ValueError as exc:
                raise ResearchManifestError(str(exc)) from exc
        metadata.update(_tabular_metadata(frame))
    elif spec["format"] == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata["json_type"] = type(payload).__name__
        metadata["top_level_keys"] = (
            sorted(str(key) for key in payload)
            if isinstance(payload, dict)
            else []
        )
    else:
        raise ResearchManifestError(
            f"Unsupported artifact format: {spec['format']}"
        )
    return metadata


def _resolve_source_revision(root: Path, source_revision: str | None) -> str:
    revision = str(source_revision or os.getenv("GITHUB_SHA", "")).strip().lower()
    if not revision:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        revision = result.stdout.strip().lower()
    if not _REVISION_PATTERN.fullmatch(revision):
        raise ResearchManifestError(
            "source_revision must be a full 40-character lowercase Git SHA"
        )
    return revision


def _feature_contract() -> dict[str, Any]:
    core = {
        "version": FEATURE_CONTRACT_VERSION,
        "generator": "src.features.compute_features.compute_features",
        "canonical_input_columns": CANONICAL_PRICE_COLUMNS,
        "output_columns": FEATURE_OUTPUT_COLUMNS,
    }
    return {**core, "sha256": _canonical_digest(core)}


def validate_research_dataset_manifest(
    manifest: dict[str, Any],
    *,
    root: str | Path = ".",
    verify_hashes: bool = True,
) -> dict[str, Any]:
    repository_root = Path(root).resolve()
    schema_version = int(manifest.get("manifest_schema_version", 0) or 0)
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise ResearchManifestError("Unsupported research manifest schema version")

    source_revision = str(manifest.get("source_revision", "")).strip().lower()
    if not _REVISION_PATTERN.fullmatch(source_revision):
        raise ResearchManifestError("Manifest source_revision is invalid")
    if manifest.get("feature_contract") != _feature_contract():
        raise ResearchManifestError("Feature contract version or declaration changed")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ResearchManifestError("Manifest artifacts must be a list")
    names = [
        str(item.get("name", ""))
        for item in artifacts
        if isinstance(item, dict)
    ]
    if set(names) != REQUIRED_ARTIFACT_NAMES or len(names) != len(set(names)):
        raise ResearchManifestError(
            "Manifest required artifact set is incomplete or duplicated"
        )

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ResearchManifestError("Manifest artifact entry is invalid")
        path = _resolve_path(repository_root, str(artifact.get("path", "")))
        _portable_path(repository_root, path)
        if not path.is_file():
            raise ResearchManifestError(
                f"Manifest artifact is missing: {artifact.get('path')}"
            )
        if verify_hashes:
            fingerprint = _artifact_fingerprint(
                path,
                str(artifact.get("format", "")),
            )
            if artifact.get("hash_mode") != fingerprint["hash_mode"]:
                raise ResearchManifestError(
                    f"Manifest hash mode mismatch: {artifact.get('name')}"
                )
            if artifact.get("byte_size") != fingerprint["byte_size"]:
                raise ResearchManifestError(
                    f"Manifest byte size mismatch: {artifact.get('name')}"
                )
            if artifact.get("sha256") != fingerprint["sha256"]:
                raise ResearchManifestError(
                    f"Manifest hash mismatch: {artifact.get('name')}"
                )
        if artifact.get("name") == "features":
            declared_columns = [
                str(column.get("name", ""))
                for column in artifact.get("columns", [])
                if isinstance(column, dict)
            ]
            validate_feature_columns(declared_columns)

    core = {key: value for key, value in manifest.items() if key != "dataset_id"}
    expected_dataset_id = _canonical_digest(core)
    if str(manifest.get("dataset_id", "")) != expected_dataset_id:
        raise ResearchManifestError(
            "Manifest dataset_id does not match its content"
        )

    return {
        "status": "pass",
        "dataset_id": expected_dataset_id,
        "source_revision": source_revision,
        "artifact_count": len(artifacts),
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "hashes_verified": bool(verify_hashes),
    }


def build_research_dataset_manifest(
    settings: Settings,
    *,
    root: str | Path = ".",
    source_revision: str | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    repository_root = Path(root).resolve()
    artifacts = sorted(
        (
            _inspect_artifact(repository_root, spec)
            for spec in _artifact_specs(settings)
        ),
        key=lambda artifact: artifact["name"],
    )
    core = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "source_revision": _resolve_source_revision(
            repository_root,
            source_revision,
        ),
        "feature_contract": _feature_contract(),
        "artifacts": artifacts,
        "safety": {
            "contains_data_payloads": False,
            "contains_secrets": False,
            "final_execution_eligible": False,
        },
    }
    manifest = {**core, "dataset_id": _canonical_digest(core)}
    validate_research_dataset_manifest(manifest, root=repository_root)

    configured_output = output_path or settings.data.research_manifest_path
    target = _resolve_path(repository_root, configured_output)
    _portable_path(repository_root, target)
    serialized = json.dumps(
        manifest,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    atomic_write_text(target, serialized + chr(10))
    return manifest


def validate_research_dataset_manifest_file(
    settings: Settings,
    *,
    root: str | Path = ".",
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    repository_root = Path(root).resolve()
    path = _resolve_path(
        repository_root,
        manifest_path or settings.data.research_manifest_path,
    )
    _portable_path(repository_root, path)
    if not path.is_file():
        raise ResearchManifestError(f"Research manifest is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResearchManifestError("Research manifest root must be an object")
    return validate_research_dataset_manifest(payload, root=repository_root)
