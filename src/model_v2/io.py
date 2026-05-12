from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib

from src.utils.io import atomic_write_json


def _mode_key(mode: str) -> str:
    return str(mode).strip().lower()


def ensure_model_dir(model_dir: str | Path) -> Path:
    out = Path(model_dir)
    out.mkdir(parents=True, exist_ok=True)
    return out


def model_artifact_path(model_dir: str | Path, mode: str) -> Path:
    return ensure_model_dir(model_dir) / f"{_mode_key(mode)}.joblib"


def model_metadata_path(model_dir: str | Path, mode: str) -> Path:
    return ensure_model_dir(model_dir) / f"{_mode_key(mode)}.meta.json"


def save_model_bundle(
    model_dir: str | Path,
    mode: str,
    model: Any,
    metadata: dict[str, Any],
) -> dict[str, str]:
    artifact_path = model_artifact_path(model_dir, mode)
    meta_path = model_metadata_path(model_dir, mode)
    joblib.dump(model, artifact_path)
    payload = {"saved_at": datetime.utcnow().isoformat(), **metadata}
    atomic_write_json(meta_path, payload)
    return {"artifact_path": str(artifact_path), "metadata_path": str(meta_path)}


def load_model_bundle(model_dir: str | Path, mode: str) -> tuple[Any | None, dict[str, Any]]:
    artifact_path = model_artifact_path(model_dir, mode)
    meta_path = model_metadata_path(model_dir, mode)
    model = None
    metadata: dict[str, Any] = {}
    if artifact_path.exists():
        try:
            model = joblib.load(artifact_path)
        except Exception:
            model = None
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}
    return model, metadata


def load_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(path: str | Path, payload: dict[str, Any]) -> str:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    return atomic_write_json(state_path, payload)
