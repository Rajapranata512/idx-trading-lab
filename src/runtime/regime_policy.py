from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import Settings

MARKET_REGIME_FEATURES = (
    "market_breadth_ma50_pct",
    "market_breadth_ma20_pct",
    "market_avg_ret20_pct",
    "market_median_atr_pct",
)


def regime_bucket_from_features(
    features: pd.DataFrame,
    settings: Settings,
    default: str = "risk_off",
) -> pd.Series:
    if features.empty:
        return pd.Series(dtype="object", index=features.index)

    if not any(col in features.columns for col in MARKET_REGIME_FEATURES):
        return pd.Series([default] * len(features), index=features.index, dtype="object")

    def _series(col: str) -> pd.Series:
        if col not in features.columns:
            return pd.Series(np.nan, index=features.index, dtype=float)
        return pd.to_numeric(features[col], errors="coerce").astype(float)

    breadth_ma50 = _series("market_breadth_ma50_pct")
    breadth_ma20 = _series("market_breadth_ma20_pct")
    avg_ret20 = _series("market_avg_ret20_pct")
    median_atr = _series("market_median_atr_pct")

    checks = (
        (breadth_ma50 >= float(settings.regime.min_breadth_ma50_pct))
        & (breadth_ma20 >= float(settings.regime.min_breadth_ma20_pct))
        & (avg_ret20 >= float(settings.regime.min_avg_ret20_pct))
        & (median_atr <= float(settings.regime.max_median_atr_pct))
    )
    labels = np.where(checks.fillna(False), "risk_on", default)
    return pd.Series(labels, index=features.index, dtype="object")
