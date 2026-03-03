from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from urllib import parse, request

import pandas as pd

from src.config import Settings, UniverseSourceSettings


def _resolve_env_value(value: str) -> str:
    txt = str(value)
    if txt.startswith("${") and txt.endswith("}") and len(txt) > 3:
        env_name = txt[2:-1].strip()
        return os.getenv(env_name, "")
    return txt


def _resolved_dict(values: dict[str, str] | None) -> dict[str, str]:
    raw = values or {}
    return {k: _resolve_env_value(v) for k, v in raw.items()}


def _extract_by_path(payload: object, path: str) -> object:
    if not path:
        return payload
    cur = payload
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return []
    return cur


def _normalize_ticker(raw: object) -> str:
    txt = str(raw).upper().strip()
    if "." in txt:
        txt = txt.split(".", 1)[0]
    return txt


def _read_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _load_members(source: UniverseSourceSettings, index_name: str, settings: Settings) -> tuple[list[str], str]:
    if not source.url:
        return [], "no_url"

    base_params = _resolved_dict(settings.data.universe_auto_update.query_params)
    source_params = _resolved_dict(source.query_params)
    params = {**base_params, **source_params}
    headers = _resolved_dict(settings.data.universe_auto_update.headers)

    url = source.url.strip()
    if params:
        connector = "&" if "?" in url else "?"
        url = f"{url}{connector}{parse.urlencode(params)}"

    req = request.Request(url=url, headers=headers)
    with request.urlopen(req, timeout=settings.data.universe_auto_update.request_timeout_seconds) as resp:
        text = resp.read().decode("utf-8")

    fmt = (source.format or "csv").strip().lower()
    if fmt == "json":
        payload = json.loads(text)
        rows = _extract_by_path(payload, source.response_data_path)
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise ValueError(f"Universe source {index_name} JSON data is not list-like")
        frame = pd.DataFrame(rows)
    else:
        frame = pd.read_csv(StringIO(text))

    if source.ticker_column not in frame.columns:
        raise ValueError(f"Universe source {index_name} missing ticker column: {source.ticker_column}")

    tickers = (
        frame[source.ticker_column]
        .dropna()
        .astype(str)
        .map(_normalize_ticker)
        .loc[lambda s: s.str.len() > 0]
        .unique()
        .tolist()
    )
    tickers = sorted(set(tickers))
    return tickers, "ok"


def maybe_auto_update_universe(settings: Settings, force: bool = False) -> dict[str, object]:
    cfg = settings.data.universe_auto_update
    universe_path = Path(settings.data.universe_csv_path)
    state_path = Path(cfg.state_path)
    now = datetime.utcnow()
    state = _read_state(state_path)

    result: dict[str, object] = {
        "enabled": bool(cfg.enabled),
        "forced": bool(force),
        "status": "skipped_disabled",
        "message": "Universe auto-update disabled",
        "universe_path": str(universe_path),
        "state_path": str(state_path),
        "updated": False,
        "attempted_at": now.isoformat(),
        "last_success_at": state.get("last_success_at", ""),
        "counts": {"lq45": 0, "idx30": 0, "combined": 0},
        "errors": [],
    }

    if (not cfg.enabled) and (not force):
        return result

    last_success = pd.to_datetime(state.get("last_success_at"), errors="coerce")
    if (not force) and pd.notna(last_success):
        elapsed = now - pd.Timestamp(last_success).to_pydatetime()
        if elapsed < timedelta(days=max(1, int(cfg.interval_days))):
            result["status"] = "skipped_interval"
            result["message"] = f"Last successful update still within {cfg.interval_days} days interval"
            return result

    lq45_members: list[str] = []
    idx30_members: list[str] = []
    source_status: dict[str, str] = {}
    errors: list[str] = []

    for index_name, source in [("LQ45", cfg.lq45), ("IDX30", cfg.idx30)]:
        try:
            members, status = _load_members(source, index_name=index_name, settings=settings)
            source_status[index_name] = status
            if index_name == "LQ45":
                lq45_members = members
            else:
                idx30_members = members
        except Exception as exc:
            source_status[index_name] = "error"
            errors.append(f"{index_name}: {exc}")

    result["errors"] = errors
    result["source_status"] = source_status

    no_url_only = source_status and all(v == "no_url" for v in source_status.values())
    if no_url_only:
        result["status"] = "skipped_no_source"
        result["message"] = "Universe source URLs are empty; keeping existing universe file"
        _write_state(
            state_path,
            {
                "last_attempt_at": now.isoformat(),
                "last_success_at": state.get("last_success_at", ""),
                "status": result["status"],
                "message": result["message"],
                "errors": errors,
                "source_status": source_status,
                "universe_path": str(universe_path),
            },
        )
        return result

    rows: list[dict[str, str]] = []
    updated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    for ticker in lq45_members:
        rows.append({"ticker": ticker, "index": "LQ45", "source": "auto_update", "updated_at": updated_at})
    for ticker in idx30_members:
        rows.append({"ticker": ticker, "index": "IDX30", "source": "auto_update", "updated_at": updated_at})

    if not rows:
        result["status"] = "failed_no_rows"
        result["message"] = "No members fetched from universe sources; keeping existing universe file"
        if cfg.fail_on_error:
            raise RuntimeError(str(result["message"]))
        _write_state(
            state_path,
            {
                "last_attempt_at": now.isoformat(),
                "last_success_at": state.get("last_success_at", ""),
                "status": result["status"],
                "message": result["message"],
                "errors": errors,
            },
        )
        return result

    frame = pd.DataFrame(rows)
    frame = frame.sort_values(["ticker", "index"]).reset_index(drop=True)
    merged = (
        frame.groupby("ticker", as_index=False)
        .agg(index=("index", lambda s: "|".join(sorted(set(s)))), source=("source", "first"), updated_at=("updated_at", "max"))
        .sort_values("ticker")
        .reset_index(drop=True)
    )

    universe_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(universe_path, index=False)

    result["updated"] = True
    result["status"] = "updated"
    result["message"] = "Universe updated successfully"
    result["counts"] = {
        "lq45": len(lq45_members),
        "idx30": len(idx30_members),
        "combined": int(merged["ticker"].nunique()),
    }
    result["last_success_at"] = now.isoformat()

    _write_state(
        state_path,
        {
            "last_attempt_at": now.isoformat(),
            "last_success_at": now.isoformat(),
            "status": result["status"],
            "message": result["message"],
            "counts": result["counts"],
            "errors": errors,
            "source_status": source_status,
            "universe_path": str(universe_path),
        },
    )
    return result
