from __future__ import annotations

import json
import os
from urllib import parse, request
from typing import Any


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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if out != out:
            return default
        return out
    except Exception:
        return default


def _fmt_float(value: Any, digits: int = 2) -> str:
    return f"{_safe_float(value):.{digits}f}"


def _fmt_optional_float(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        out = float(value)
        if out != out:
            return "-"
        return f"{out:.{digits}f}"
    except Exception:
        return "-"


def _fmt_price(value: Any) -> str:
    price = _safe_float(value)
    if abs(price - round(price)) < 0.005:
        return f"{price:.0f}"
    return f"{price:.2f}"


def _is_recommended(row: dict[str, Any]) -> bool:
    value = row.get("shadow_recommended", row.get("recommended", False))
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _is_trained_model_signal(row: dict[str, Any]) -> bool:
    return str(row.get("shadow_model_source", "")).strip().lower() == "model"


def _format_shadow_pick(idx: int, row: dict[str, Any]) -> list[str]:
    mode = str(row.get("mode", "-")).upper()
    ticker = str(row.get("ticker", "-")).upper()
    recommended = "YES" if _is_recommended(row) else "NO"
    return [
        f"{idx}. {mode}:{ticker}",
        (
            f"   score={_fmt_float(row.get('score'), 2)} "
            f"p(win)={_fmt_optional_float(row.get('shadow_p_win'), 4)} "
            f"E[R]={_fmt_optional_float(row.get('shadow_expected_r'), 4)} "
            f"recommended={recommended}"
        ),
        (
            f"   entry={_fmt_price(row.get('entry'))} "
            f"stop={_fmt_price(row.get('stop'))} "
            f"tp1={_fmt_price(row.get('tp1'))}"
        ),
    ]


def build_model_v2_shadow_message(
    payload: dict[str, Any],
    rollout_pct: int = 0,
    source_label: str = "reports/model_v2_shadow_signals.json",
) -> str:
    signals = payload.get("signals", [])
    signals = signals if isinstance(signals, list) else []
    generated_at = str(payload.get("generated_at", "-"))
    model_signals = [
        row for row in signals
        if isinstance(row, dict) and _is_trained_model_signal(row)
    ]
    blocked = [
        row for row in signals
        if isinstance(row, dict) and not _is_trained_model_signal(row)
    ]
    recommended = [row for row in model_signals if _is_recommended(row)]
    rejected = [row for row in model_signals if not _is_recommended(row)]
    model_status = "READY" if model_signals else "BLOCKED"

    lines = [
        "IDX Model v2 Shadow Signal | pre-open",
        f"Source: {source_label} {generated_at}",
        f"Model status: {model_status}",
        f"Note: ini shadow monitoring, bukan final/live execution signal. Rollout v2 masih {int(rollout_pct)}%.",
        "",
        "Direkomendasikan V2 terverifikasi:",
    ]
    if recommended:
        for idx, row in enumerate(recommended, start=1):
            lines.extend(_format_shadow_pick(idx, row))
    else:
        lines.append("(tidak ada)")

    lines.extend(["", "Tidak direkomendasikan V2 terverifikasi:"])
    if rejected:
        for idx, row in enumerate(rejected, start=1):
            lines.extend(_format_shadow_pick(idx, row))
    else:
        lines.append("(tidak ada)")

    if blocked:
        lines.extend(
            [
                "",
                f"Diblokir: {len(blocked)} kandidat tidak memakai model terlatih.",
                "Tidak ada p(win), E[R], atau rekomendasi yang diterbitkan dari fallback.",
            ]
        )

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


def build_preopen_auction_message(payload: dict[str, Any], max_items_per_section: int = 5) -> str:
    signals = payload.get("signals", [])
    signals = [row for row in signals if isinstance(row, dict)] if isinstance(signals, list) else []
    phase = str(payload.get("phase", "-")).upper()
    as_of = str(payload.get("as_of", "-"))
    status = str(payload.get("status", "blocked")).upper()
    lines = [
        f"IDX Pre-Open Auction | {phase} | SHADOW",
        f"As of: {as_of}",
        f"Status: {status} | Execution: DISABLED",
        "Catatan: analisis IEP/IEV dan order book, bukan perintah beli/jual.",
    ]
    if status != "READY":
        reasons = payload.get("block_reasons", []) or [payload.get("block_reason", "unknown")]
        reason_text = ", ".join(str(reason) for reason in reasons if str(reason)) or "unknown"
        lines.extend(["", "NO_TRADE", f"Alasan: {reason_text}"])
        return "\n".join(lines)

    def add_section(title: str, classifications: set[str]) -> None:
        rows = [row for row in signals if str(row.get("shadow_classification", "")) in classifications]
        lines.extend(["", title])
        if not rows:
            lines.append("(tidak ada)")
            return
        for index, row in enumerate(rows[: max(1, int(max_items_per_section))], start=1):
            ticker = str(row.get("ticker", "-")).upper()
            classification = str(row.get("shadow_classification", "-"))
            lines.append(
                f"{index}. {ticker} | {classification} | "
                f"IEP={_fmt_optional_float(row.get('iep_gap_bps'), 0)}bps "
                f"IEV/ADV={_fmt_optional_float(row.get('iev_to_adv20_pct'), 2)}%"
            )
            lines.append(
                f"   P(open up)={_fmt_optional_float(row.get('p_open_up'), 3)} "
                f"P(follow up)={_fmt_optional_float(row.get('p_follow_up_15m'), 3)} "
                f"P(fake up)={_fmt_optional_float(row.get('p_fake_gap_up_15m'), 3)} "
                f"EV15={_fmt_optional_float(row.get('expected_return_15m_bps'), 0)}bps"
            )

    add_section("Pantauan naik terverifikasi model:", {"UP_FOLLOW_THROUGH"})
    add_section("Risiko fake gap:", {"FAKE_UP_RISK", "FAKE_DOWN_RISK"})
    add_section("Risiko turun / hindari:", {"DOWN_FOLLOW_THROUGH"})
    uncertain_count = sum(
        str(row.get("shadow_classification", "")) in {"UNCERTAIN", "NO_TRADE"}
        for row in signals
    )
    if uncertain_count:
        lines.extend(["", f"Tidak pasti/NO_TRADE: {uncertain_count} saham."])
    return "\n".join(lines)