from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


def _signal_lines(signals: pd.DataFrame, limit: int = 3) -> list[str]:
    if signals.empty:
        return []
    rows = signals.head(limit).copy()
    lines: list[str] = []
    for _, r in rows.iterrows():
        lines.append(
            f"- {str(r.get('ticker', ''))} ({str(r.get('mode', ''))}) "
            f"score={r.get('score', '')} entry={r.get('entry', '')} stop={r.get('stop', '')} "
            f"tp1={r.get('tp1', '')} tp2={r.get('tp2', '')} size={r.get('size', '')}"
        )
    return lines


def write_beginner_coaching_note(
    out_path: str | Path,
    run_id: str,
    status: str,
    action_reason: str,
    signals: pd.DataFrame,
) -> str:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    is_trade_ok = str(status).upper() == "SUCCESS" and not signals.empty
    top_lines = _signal_lines(signals, limit=1 if is_trade_ok else 0)
    if not top_lines and is_trade_ok:
        top_lines = _signal_lines(signals, limit=1)

    note = [
        "# Beginner Coaching Note",
        "",
        f"- generated_at: {datetime.utcnow().isoformat()}",
        f"- run_id: {run_id}",
        f"- status: {status}",
        f"- action_reason: {action_reason}",
        "",
        "## Rule Inti Hari Ini",
    ]
    if is_trade_ok:
        note.extend(
            [
                "1. Entry hanya 1 posisi terbaik.",
                "2. Pasang stop-loss saat entry, jangan digeser ke bawah.",
                "3. Jika harga jauh dari entry plan, tunggu setup berikutnya.",
                "",
                "## Kandidat Utama",
                *top_lines,
            ]
        )
    else:
        note.extend(
            [
                "1. NO_TRADE adalah keputusan valid saat kondisi tidak aman.",
                "2. Jangan paksakan entry di luar sinyal sistem.",
                "3. Fokus menjaga modal dan disiplin eksekusi.",
            ]
        )

    note.extend(
        [
            "",
            "## Jurnal Singkat",
            "- Emosi utama hari ini:",
            "- Apakah saya mengikuti SOP 100%? (ya/tidak):",
            "- Catatan perbaikan besok:",
            "",
        ]
    )

    out.write_text("\n".join(note), encoding="utf-8")
    return str(out)
