from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings
from src.universe.updater import maybe_auto_update_universe as _legacy_auto_update


_HISTORY_COLUMNS = {
    "ticker",
    "index",
    "effective_from",
    "effective_until",
    "source",
    "source_document",
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def _normalize_history(history: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(_HISTORY_COLUMNS - set(history.columns))
    if missing:
        raise ValueError(f"Universe history is missing columns: {missing}")

    frame = history.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["index"] = frame["index"].astype(str).str.upper().str.strip()
    frame["effective_from"] = pd.to_datetime(frame["effective_from"], errors="coerce")
    frame["effective_until"] = pd.to_datetime(frame["effective_until"], errors="coerce")
    frame["source"] = frame["source"].astype(str).str.strip()
    frame["source_document"] = frame["source_document"].astype(str).str.strip()

    invalid = (
        frame["ticker"].str.fullmatch(r"[A-Z]{4,6}").fillna(False).eq(False)
        | ~frame["index"].isin(["LQ45", "IDX30"])
        | frame["effective_from"].isna()
        | frame["effective_until"].isna()
        | frame["effective_until"].lt(frame["effective_from"])
        | frame["source"].eq("")
        | frame["source_document"].eq("")
    )
    if bool(invalid.any()):
        sample = frame.loc[
            invalid,
            ["ticker", "index", "effective_from", "effective_until", "source"],
        ].head(5)
        raise ValueError(
            "Universe history contains invalid rows. Sample: "
            + json.dumps(sample.astype(str).to_dict(orient="records"), ensure_ascii=True)
        )

    duplicate = frame.duplicated(
        subset=["ticker", "index", "effective_from", "effective_until"],
        keep=False,
    )
    if bool(duplicate.any()):
        raise ValueError("Universe history contains duplicate membership rows")
    return frame


def active_universe_from_history(
    history_path: str | Path,
    as_of: date,
    expected_lq45: int,
    expected_idx30: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = Path(history_path)
    if not path.exists():
        raise FileNotFoundError(f"Universe history file not found: {path}")

    history = _normalize_history(pd.read_csv(path))
    as_of_ts = pd.Timestamp(as_of)
    active = history[
        history["effective_from"].le(as_of_ts)
        & history["effective_until"].ge(as_of_ts)
    ].copy()
    if active.empty:
        latest_until = history["effective_until"].max()
        latest_text = latest_until.date().isoformat() if pd.notna(latest_until) else "unknown"
        raise ValueError(
            f"No active universe snapshot for {as_of.isoformat()}; latest snapshot ends {latest_text}"
        )

    duplicate_active = active.duplicated(subset=["ticker", "index"], keep=False)
    if bool(duplicate_active.any()):
        raise ValueError("Overlapping universe periods produce duplicate active memberships")

    counts = {
        "lq45": int(active.loc[active["index"].eq("LQ45"), "ticker"].nunique()),
        "idx30": int(active.loc[active["index"].eq("IDX30"), "ticker"].nunique()),
    }
    if counts["lq45"] != int(expected_lq45):
        raise ValueError(
            f"Active LQ45 snapshot has {counts['lq45']} members; expected {expected_lq45}"
        )
    if counts["idx30"] != int(expected_idx30):
        raise ValueError(
            f"Active IDX30 snapshot has {counts['idx30']} members; expected {expected_idx30}"
        )

    periods = active[["effective_from", "effective_until"]].drop_duplicates()
    if len(periods) != 1:
        raise ValueError("Active LQ45 and IDX30 snapshots must share one effective period")
    effective_from = pd.Timestamp(periods.iloc[0]["effective_from"]).date()
    effective_until = pd.Timestamp(periods.iloc[0]["effective_until"]).date()

    merged = (
        active.groupby("ticker", as_index=False)
        .agg(
            index=("index", lambda values: "|".join(sorted(set(values)))),
            effective_from=("effective_from", "min"),
            effective_until=("effective_until", "max"),
            source=("source", lambda values: "|".join(sorted(set(values)))),
            source_document=("source_document", lambda values: "|".join(sorted(set(values)))),
        )
        .sort_values("ticker")
        .reset_index(drop=True)
    )
    merged["effective_from"] = pd.to_datetime(merged["effective_from"]).dt.date.astype(str)
    merged["effective_until"] = pd.to_datetime(merged["effective_until"]).dt.date.astype(str)
    counts["combined"] = int(merged["ticker"].nunique())
    metadata = {
        "as_of": as_of.isoformat(),
        "effective_from": effective_from.isoformat(),
        "effective_until": effective_until.isoformat(),
        "days_until_expiry": int((effective_until - as_of).days),
        "counts": counts,
        "source_documents": sorted(active["source_document"].unique().tolist()),
    }
    return merged, metadata


def _same_universe(existing_path: Path, expected: pd.DataFrame) -> bool:
    if not existing_path.exists():
        return False
    try:
        existing = pd.read_csv(existing_path)
    except Exception:
        return False
    required = list(expected.columns)
    if any(column not in existing.columns for column in required):
        return False
    left = existing[required].fillna("").astype(str).sort_values(required).reset_index(drop=True)
    right = expected[required].fillna("").astype(str).sort_values(required).reset_index(drop=True)
    return left.equals(right)


def maybe_auto_update_universe(
    settings: Settings,
    force: bool = False,
    as_of: date | None = None,
) -> dict[str, Any]:
    cfg = settings.data.universe_auto_update
    universe_path = Path(settings.data.universe_csv_path)
    state_path = Path(cfg.state_path)
    history_path = Path(cfg.history_path)
    now = datetime.utcnow()
    effective_as_of = as_of or datetime.now().date()

    if not cfg.enabled and not force:
        return {
            "enabled": False,
            "forced": False,
            "status": "skipped_disabled",
            "message": "Universe auto-update disabled",
            "updated": False,
            "universe_path": str(universe_path),
            "history_path": str(history_path),
        }

    try:
        active, metadata = active_universe_from_history(
            history_path=history_path,
            as_of=effective_as_of,
            expected_lq45=int(cfg.expected_lq45_members),
            expected_idx30=int(cfg.expected_idx30_members),
        )
        updated = not _same_universe(universe_path, active)
        if updated:
            universe_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = universe_path.with_suffix(universe_path.suffix + ".tmp")
            active.to_csv(tmp_path, index=False)
            tmp_path.replace(universe_path)

        status = "updated_from_history" if updated else "validated_current"
        result: dict[str, Any] = {
            "enabled": True,
            "forced": bool(force),
            "status": status,
            "message": "Point-in-time IDX universe snapshot is current and valid",
            "updated": updated,
            "attempted_at": now.isoformat(),
            "last_success_at": now.isoformat(),
            "universe_path": str(universe_path),
            "history_path": str(history_path),
            **metadata,
            "errors": [],
        }
        _write_json(state_path, result)
        return result
    except Exception as exc:
        has_remote_source = bool(str(cfg.lq45.url).strip() or str(cfg.idx30.url).strip())
        if has_remote_source and not bool(cfg.fail_on_stale):
            return _legacy_auto_update(settings=settings, force=force)

        result = {
            "enabled": True,
            "forced": bool(force),
            "status": "blocked_stale_or_invalid",
            "message": str(exc),
            "updated": False,
            "attempted_at": now.isoformat(),
            "last_success_at": "",
            "universe_path": str(universe_path),
            "history_path": str(history_path),
            "counts": {"lq45": 0, "idx30": 0, "combined": 0},
            "errors": [str(exc)],
        }
        _write_json(state_path, result)
        if bool(cfg.fail_on_error) or bool(cfg.fail_on_stale):
            raise RuntimeError(f"Universe freshness gate blocked run: {exc}") from exc
        return result
