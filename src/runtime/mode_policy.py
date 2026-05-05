from __future__ import annotations

from typing import Any

import pandas as pd

from src.config import Settings

SUPPORTED_MODES = ("t1", "swing")


def supported_modes() -> list[str]:
    return list(SUPPORTED_MODES)


def active_modes(settings: Settings) -> list[str]:
    active: list[str] = []
    for raw_mode in settings.pipeline.active_modes:
        mode = str(raw_mode).strip().lower()
        if mode in SUPPORTED_MODES and mode not in active:
            active.append(mode)
    return active or ["swing", "t1"]


def inactive_modes(settings: Settings) -> list[str]:
    active = set(active_modes(settings))
    return [mode for mode in SUPPORTED_MODES if mode not in active]


def mode_activation_payload(settings: Settings) -> dict[str, Any]:
    active = active_modes(settings)
    inactive = inactive_modes(settings)
    return {
        "active_modes": active,
        "inactive_modes": inactive,
        "swing_only": active == ["swing"],
    }


def zero_metrics_payload() -> dict[str, float]:
    return {
        "WinRate": 0.0,
        "ProfitFactor": 0.0,
        "Expectancy": 0.0,
        "Trades": 0,
        "CAGR": 0.0,
        "MaxDD": 0.0,
    }


def empty_mode_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.iloc[0:0].copy()
