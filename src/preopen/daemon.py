from __future__ import annotations

import json
import time as time_module
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import Settings, load_settings
from src.notify import build_preopen_auction_message, send_telegram_message
from src.preopen.data import normalize_as_of
from src.preopen.pipeline import run_preopen_auction_shadow
from src.utils.io import atomic_write_json


def _clock_on_date(base: pd.Timestamp, value: str) -> pd.Timestamp:
    clock = pd.Timestamp(value).time()
    return pd.Timestamp(datetime.combine(base.date(), clock), tz=base.tzinfo)


def _load_scheduler_state(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def due_notification_phase(
    now: datetime | pd.Timestamp | str,
    settings: Settings,
    state: dict[str, Any] | None = None,
) -> str:
    local_now = normalize_as_of(now, settings.data.timezone)
    if local_now.weekday() >= 5:
        return ""
    cfg = settings.preopen_auction
    preliminary = _clock_on_date(local_now, cfg.preliminary_time_local)
    cutoff = _clock_on_date(local_now, cfg.decision_cutoff_time_local)
    market_open = _clock_on_date(local_now, cfg.market_open_time_local)
    if local_now < preliminary or local_now >= market_open:
        return ""

    payload = state or {}
    same_date = str(payload.get("session_date", "")) == local_now.date().isoformat()
    delivered = set(payload.get("delivered_phases", [])) if same_date else set()
    attempted = set(payload.get("attempted_phases", [])) if same_date else set()
    completed = delivered | attempted
    if local_now < cutoff and "preliminary" not in completed:
        return "preliminary"
    if local_now >= cutoff and "final_preopen" not in completed:
        return "final_preopen"
    return ""


def run_preopen_scheduler_tick(
    settings: Settings,
    now: datetime | pd.Timestamp | str | None = None,
    send_telegram: bool = False,
    state_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local_now = normalize_as_of(now, settings.data.timezone)
    state = state_override if state_override is not None else _load_scheduler_state(
        settings.preopen_auction.scheduler_state_path
    )
    phase = due_notification_phase(local_now, settings, state=state)
    if not phase:
        return {
            "status": "idle",
            "as_of": local_now.isoformat(),
            "sent": False,
            "phase": "",
        }

    report = run_preopen_auction_shadow(settings=settings, as_of=local_now)
    message = build_preopen_auction_message(report)
    sent = False
    if send_telegram:
        same_date = state.get("session_date") == local_now.date().isoformat()
        attempted = set(state.get("attempted_phases", [])) if same_date else set()
        delivered = set(state.get("delivered_phases", [])) if same_date else set()
        failed = set(state.get("failed_phases", [])) if same_date else set()
        attempted.add(phase)
        state = {
            "session_date": local_now.date().isoformat(),
            "attempted_phases": sorted(attempted),
            "delivered_phases": sorted(delivered),
            "failed_phases": sorted(failed),
            "last_attempt_at": local_now.isoformat(),
            "last_phase": phase,
            "last_report_status": str(report.get("status", "")),
        }
        target = Path(settings.preopen_auction.scheduler_state_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, state)

        sent = send_telegram_message(
            message=message,
            bot_token_env=settings.notifications.telegram_bot_token_env,
            chat_id_env=settings.notifications.telegram_chat_id_env,
        )
        if sent:
            delivered.add(phase)
            failed.discard(phase)
        else:
            failed.add(phase)
        state["delivered_phases"] = sorted(delivered)
        state["failed_phases"] = sorted(failed)
        state["last_delivery_at"] = local_now.isoformat() if sent else ""
        atomic_write_json(target, state)

    return {
        "status": "sent" if sent else ("send_failed" if send_telegram else "dry_run"),
        "as_of": local_now.isoformat(),
        "phase": phase,
        "sent": bool(sent),
        "report_status": str(report.get("status", "")),
        "message": message,
    }


def run_preopen_daemon(
    settings_path: str = "config/settings.json",
    send_telegram: bool = False,
    max_loops: int | None = None,
    now_fn: Callable[[], datetime] | None = None,
    sleep_fn: Callable[[float], None] = time_module.sleep,
) -> dict[str, Any]:
    settings = load_settings(settings_path)
    timezone = ZoneInfo(settings.data.timezone)
    clock = now_fn or (lambda: datetime.now(tz=timezone))
    loops = 0
    deliveries = 0
    last_result: dict[str, Any] = {"status": "not_started"}
    dry_state: dict[str, Any] = {}
    while max_loops is None or loops < max(1, int(max_loops)):
        local_now = normalize_as_of(clock(), settings.data.timezone)
        last_result = run_preopen_scheduler_tick(
            settings=settings,
            now=local_now,
            send_telegram=send_telegram,
            state_override=None if send_telegram else dry_state,
        )
        if not send_telegram and last_result.get("phase"):
            attempted = set(dry_state.get("attempted_phases", []))
            attempted.add(str(last_result["phase"]))
            dry_state = {
                "session_date": local_now.date().isoformat(),
                "attempted_phases": sorted(attempted),
            }
        loops += 1
        deliveries += int(bool(last_result.get("sent")))
        market_open = _clock_on_date(local_now, settings.preopen_auction.market_open_time_local)
        if local_now >= market_open:
            break
        sleep_fn(max(1, int(settings.preopen_auction.scheduler_poll_seconds)))
    return {
        "status": "completed",
        "loops": loops,
        "deliveries": deliveries,
        "send_telegram": bool(send_telegram),
        "last_result": last_result,
    }