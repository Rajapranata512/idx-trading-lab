from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.notify.telegram import send_telegram_message
from src.report.render_report import write_signal_json


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
                "confidence": 0.8,
                "model_version": "model_v1",
                "reason_codes": ["CUSTOM_REASON"],
                "gate_flags": {"final_ok": True},
            }
        ],
    }
    out.write_text(json.dumps(payload), encoding="utf-8")
    loaded = json.loads(Path(out).read_text(encoding="utf-8"))
    row = loaded["signals"][0]
    assert {"ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size", "reason"} <= set(row.keys())
    assert {"confidence", "model_version", "reason_codes", "gate_flags"} <= set(row.keys())


def test_write_signal_json_adds_standard_fields(tmp_path):
    out = tmp_path / "daily_signal.json"
    df = pd.DataFrame(
        [
            {
                "ticker": "BBCA",
                "mode": "swing",
                "score": 72.5,
                "entry": 10000,
                "stop": 9800,
                "tp1": 10200,
                "tp2": 10400,
                "size": 100,
                "reason": "Trend MA50 + momentum 20D + ATR expansion",
            }
        ]
    )
    write_signal_json(df=df, out_path=str(out), model_version="model_v1_with_v2_shadow")
    payload = json.loads(out.read_text(encoding="utf-8"))
    row = payload["signals"][0]
    assert row["model_version"] == "model_v1_with_v2_shadow"
    assert 0 <= float(row["confidence"]) <= 1
    assert isinstance(row["reason_codes"], list)
    assert isinstance(row["gate_flags"], dict)
