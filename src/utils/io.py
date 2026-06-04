from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{out.name}.",
        suffix=".tmp",
        dir=str(out.parent),
        text=True,
    )
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(out)
        return str(out)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


import math

def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(_sanitize_for_json(v) for v in obj)
    return obj

def atomic_write_json(path: str | Path, payload: Any) -> str:
    clean_payload = _sanitize_for_json(payload)
    return atomic_write_text(
        path,
        json.dumps(clean_payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
