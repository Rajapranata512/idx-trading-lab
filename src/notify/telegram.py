from __future__ import annotations

import json
import os
from urllib import parse, request


def build_daily_message(
    run_id: str,
    top_lines: list[str],
    risk_summary: str,
    data_status: str,
) -> str:
    lines = [
        f"IDX Daily Signal | run_id={run_id}",
        data_status,
        risk_summary,
        "Top picks:",
    ]
    lines.extend(top_lines or ["(no picks)"])
    return "\n".join(lines)


def send_telegram_message(message: str, bot_token_env: str, chat_id_env: str) -> bool:
    token = os.getenv(bot_token_env, "").strip()
    chat_id = os.getenv(chat_id_env, "").strip()
    if not token or not chat_id:
        return False

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    req = request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body)
        return bool(data.get("ok"))
    except Exception:
        return False
