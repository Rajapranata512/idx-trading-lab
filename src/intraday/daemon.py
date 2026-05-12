from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import load_settings
from src.intraday.pipeline import run_intraday_once


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def run_intraday_daemon(
    settings_path: str = "config/settings.json",
    max_loops: int = 0,
) -> None:
    """Run intraday polling loop with reconnect/backoff behavior.

    Set `max_loops` > 0 for test/dev bounded runs.
    """
    state_path = Path("reports/intraday_daemon_state.json")
    loops = 0
    consecutive_errors = 0

    while True:
        loops += 1
        settings = load_settings(settings_path)
        cfg = settings.data.intraday
        started_at = datetime.utcnow().isoformat()
        try:
            result = run_intraday_once(settings=settings, lookback_minutes=cfg.lookback_minutes)
            consecutive_errors = 0
            _write_state(
                state_path,
                {
                    "status": "ok",
                    "started_at": started_at,
                    "finished_at": datetime.utcnow().isoformat(),
                    "timeframe": cfg.timeframe,
                    "poll_seconds": int(cfg.poll_seconds),
                    "consecutive_errors": consecutive_errors,
                    "result": result,
                },
            )
            sleep_sec = max(5, int(cfg.poll_seconds))
        except Exception as exc:
            consecutive_errors += 1
            backoff_base = max(1, int(cfg.reconnect_backoff_seconds))
            max_backoff = max(backoff_base, int(cfg.reconnect_max_backoff_seconds))
            sleep_sec = min(max_backoff, backoff_base * (2 ** max(0, consecutive_errors - 1)))
            _write_state(
                state_path,
                {
                    "status": "error",
                    "started_at": started_at,
                    "finished_at": datetime.utcnow().isoformat(),
                    "timeframe": cfg.timeframe,
                    "consecutive_errors": consecutive_errors,
                    "sleep_seconds": sleep_sec,
                    "error": str(exc),
                },
            )
            if consecutive_errors >= int(cfg.reconnect_max_attempts):
                # Reset error streak to prevent unbounded backoff; keep daemon alive.
                consecutive_errors = 0

        if max_loops > 0 and loops >= max_loops:
            break
        time.sleep(sleep_sec)

