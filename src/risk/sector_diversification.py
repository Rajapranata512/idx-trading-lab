"""Sector diversification enforcement for portfolio construction.

Ensures no single sector exceeds the configured exposure cap,
preventing concentration risk that can cause catastrophic drawdowns.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import pandas as pd


def load_sector_map(universe_csv_path: str | Path) -> dict[str, str]:
    """Load ticker → sector mapping from universe CSV."""
    path = Path(universe_csv_path)
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    if "ticker" not in df.columns:
        return {}
    for col in ["sector", "industry", "segment"]:
        if col in df.columns:
            return dict(zip(
                df["ticker"].astype(str).str.upper().str.strip(),
                df[col].astype(str).str.strip(),
            ))
    return {}


def enforce_sector_cap(
    candidates: pd.DataFrame,
    sector_map: dict[str, str],
    max_sector_pct: float = 35.0,
    max_positions: int = 5,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Filter candidates to enforce sector diversification cap.

    Greedily selects top candidates (by score/rank) while ensuring
    no sector exceeds max_sector_pct of total selected positions.

    Parameters
    ----------
    candidates : DataFrame
        Must have 'ticker' column. Assumed sorted by priority (best first).
    sector_map : dict
        Ticker → sector mapping.
    max_sector_pct : float
        Maximum % of positions in any single sector.
    max_positions : int
        Maximum total positions to select.

    Returns
    -------
    (filtered_df, diagnostics)
    """
    if candidates.empty:
        return candidates.copy(), {"status": "empty", "removed": []}

    df = candidates.copy()
    df["_sector"] = df["ticker"].astype(str).str.upper().str.strip().map(sector_map).fillna("unknown")

    selected_idx: list[int] = []
    sector_counts: dict[str, int] = {}
    removed: list[dict[str, str]] = []

    max_per_sector = max(1, int((max_positions * max_sector_pct) / 100.0))

    for idx, row in df.iterrows():
        if len(selected_idx) >= max_positions:
            break
        sector = str(row["_sector"])
        current_count = sector_counts.get(sector, 0)
        if current_count >= max_per_sector:
            removed.append({
                "ticker": str(row.get("ticker", "")),
                "sector": sector,
                "reason": f"sector_cap ({current_count}/{max_per_sector})",
            })
            continue
        selected_idx.append(idx)
        sector_counts[sector] = current_count + 1

    result = df.loc[selected_idx].copy()
    result.drop(columns=["_sector"], inplace=True, errors="ignore")

    diagnostics = {
        "status": "ok",
        "selected_count": len(selected_idx),
        "removed_count": len(removed),
        "removed": removed[:10],
        "sector_distribution": {
            k: v for k, v in sorted(sector_counts.items(), key=lambda x: -x[1])
        },
        "max_per_sector": max_per_sector,
    }
    return result, diagnostics
