from __future__ import annotations

import pandas as pd

from src.strategy.ranker import rank_all_modes


def score_universe(df: pd.DataFrame, min_avg_volume_20d: float = 200000, top_n: int = 20) -> pd.DataFrame:
    """Backward-compatible wrapper returning combined top picks."""
    top_n_per_mode = max(1, top_n // 2)
    _, _, combined = rank_all_modes(
        features=df,
        min_avg_volume_20d=min_avg_volume_20d,
        top_n_per_mode=top_n_per_mode,
    )
    return combined.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
