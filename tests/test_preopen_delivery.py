from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.preopen_delivery_guard import decide_preopen_delivery
from src.cli import _shadow_report_freshness, send_model_v2_shadow_telegram_step
from src.config import load_settings


def _run(
    run_id: int,
    created_at: str,
    status: str,
    conclusion: str | None,
) -> dict:
    return {
        "id": run_id,
        "created_at": created_at,
        "status": status,
        "conclusion": conclusion,
    }


def test_delivery_guard_skips_after_successful_run_on_jakarta_date():
    result = decide_preopen_delivery(
        runs=[_run(10, "2026-07-20T01:06:00Z", "completed", "success")],
        current_run_id=11,
        delivery_date="2026-07-20",
    )

    assert result["should_send"] is False
    assert result["reason"] == "already_delivered"
    assert result["previous_run_id"] == 10


def test_delivery_guard_skips_while_another_delivery_is_active():
    result = decide_preopen_delivery(
        runs=[_run(10, "2026-07-20T01:06:00Z", "in_progress", None)],
        current_run_id=11,
        delivery_date="2026-07-20",
    )

    assert result["should_send"] is False
    assert result["reason"] == "delivery_run_active"


def test_delivery_guard_retries_after_failed_run_and_ignores_current_run():
    result = decide_preopen_delivery(
        runs=[
            _run(10, "2026-07-20T01:06:00Z", "completed", "failure"),
            _run(11, "2026-07-20T01:25:00Z", "in_progress", None),
        ],
        current_run_id=11,
        delivery_date="2026-07-20",
    )

    assert result["should_send"] is True
    assert result["reason"] == "delivery_missing"


def test_shadow_freshness_allows_friday_data_on_monday():
    result = _shadow_report_freshness(
        {"data_date": "2026-07-17"},
        max_age_days=5,
        today=datetime(2026, 7, 20, 8, 0, 0),
    )

    assert result["fresh"] is True
    assert result["age_days"] == 3


def test_shadow_telegram_step_blocks_stale_report(tmp_path: Path):
    report = tmp_path / "shadow.json"
    report.write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00",
                "data_date": "2026-01-01",
                "signals": [],
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings("config/settings.json")

    result = send_model_v2_shadow_telegram_step(
        settings=settings,
        shadow_path=str(report),
        dry_run=True,
        max_report_age_days=1,
    )

    assert result["ok"] is False
    assert result["status"] == "stale_shadow_report"
