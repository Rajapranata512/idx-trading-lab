from __future__ import annotations

import json
from pathlib import Path

from src.notify.telegram import send_telegram_message


def test_send_telegram_returns_false_without_env():
    ok = send_telegram_message(
        message="test",
        bot_token_env="MISSING_BOT_TOKEN",
        chat_id_env="MISSING_CHAT_ID",
    )
    assert ok is False


def test_signal_json_contract(tmp_path):
    out = tmp_path / "daily_signal.json"
    payload = {
        "generated_at": "2026-01-01T00:00:00",
        "signals": [
            {
                "ticker": "BBCA",
                "mode": "t1",
                "score": 80.0,
                "entry": 10000,
                "stop": 9800,
                "tp1": 10200,
                "tp2": 10400,
                "size": 100,
                "reason": "test",
            }
        ],
    }
    out.write_text(json.dumps(payload), encoding="utf-8")
    loaded = json.loads(Path(out).read_text(encoding="utf-8"))
    row = loaded["signals"][0]
    assert {"ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size", "reason"} <= set(row.keys())
