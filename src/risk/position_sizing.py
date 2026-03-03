from __future__ import annotations

import pandas as pd

from src.config import RiskSettings
from src.risk.manager import propose_trade_plan as propose_trade_plan_v2


def propose_trade_plan(
    picks: pd.DataFrame,
    account_size_idr: float,
    risk_per_trade_pct: float = 1.0,
) -> pd.DataFrame:
    """Backward-compatible wrapper on top of v2 risk manager."""
    settings = RiskSettings(
        account_size_idr=account_size_idr,
        risk_per_trade_pct=risk_per_trade_pct,
    )
    df = propose_trade_plan_v2(picks, settings)
    if "tp2" in df.columns:
        df["target"] = df["tp2"]
    if "size" in df.columns and "shares" not in df.columns:
        df["shares"] = df["size"]
    return df
