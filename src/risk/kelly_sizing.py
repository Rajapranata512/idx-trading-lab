"""Dynamic position sizing using fractional Kelly Criterion.

Calculates optimal lot size based on calibrated win probability and
reward/risk ratio, capped to prevent over-concentration.
"""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd


def kelly_fraction(p_win: float, avg_win_r: float = 1.0, avg_loss_r: float = 1.0) -> float:
    """Compute Kelly fraction: f* = (p*b - q) / b."""
    p = float(np.clip(p_win, 0.01, 0.99))
    q = 1.0 - p
    b = max(float(avg_win_r) / max(float(avg_loss_r), 1e-9), 0.01)
    return float((p * b - q) / b)


def compute_dynamic_size(
    p_win: float, account_size: float, risk_per_trade_pct: float,
    entry_price: float, stop_price: float, lot_size: int = 100,
    avg_win_r: float = 1.5, avg_loss_r: float = 1.0,
    kelly_fraction_mult: float = 0.5, max_kelly_mult: float = 1.5,
    min_lots: int = 1,
) -> dict[str, Any]:
    """Calculate position size using half-Kelly."""
    entry_price = max(float(entry_price), 1.0)
    stop_price = max(float(stop_price), 0.0)
    risk_per_share = max(entry_price - stop_price, entry_price * 0.005, 1.0)

    base_risk_budget = account_size * (risk_per_trade_pct / 100.0)
    base_shares = base_risk_budget / risk_per_share
    base_lots = max(min_lots, int(base_shares // lot_size))

    kf = kelly_fraction(p_win, avg_win_r, avg_loss_r)
    kf_adj = kf * kelly_fraction_mult

    if kf_adj <= 0:
        return {"qty": 0, "lots": 0, "risk_idr": 0.0, "kelly_raw": round(kf, 6),
                "kelly_adj": round(kf_adj, 6), "multiplier": 0.0,
                "sizing_reason": "negative_edge", "base_lots": base_lots}

    kelly_mult = kf_adj / max(risk_per_trade_pct / 100.0, 1e-9)
    kelly_mult = float(np.clip(kelly_mult, 0.5, max_kelly_mult))

    adj_lots = max(min_lots, int(base_lots * kelly_mult))
    adj_shares = adj_lots * lot_size
    risk_idr = risk_per_share * adj_shares

    if kelly_mult >= max_kelly_mult * 0.95:
        reason = "kelly_capped"
    elif kelly_mult >= 1.0:
        reason = "kelly_upsize"
    elif kelly_mult >= 0.75:
        reason = "kelly_base"
    else:
        reason = "kelly_downsize"

    return {"qty": int(adj_shares), "lots": int(adj_lots),
            "risk_idr": round(float(risk_idr), 2), "kelly_raw": round(float(kf), 6),
            "kelly_adj": round(float(kf_adj), 6), "multiplier": round(float(kelly_mult), 4),
            "sizing_reason": reason, "base_lots": int(base_lots)}


def apply_dynamic_sizing(
    candidates: pd.DataFrame, account_size: float, risk_per_trade_pct: float,
    lot_size: int = 100, avg_win_r: float = 1.5, avg_loss_r: float = 1.0,
    kelly_fraction_mult: float = 0.5, max_kelly_mult: float = 1.5,
) -> pd.DataFrame:
    """Apply dynamic sizing to all candidate signals."""
    if candidates.empty:
        return candidates.copy()
    df = candidates.copy()
    results = []
    for _, row in df.iterrows():
        sizing = compute_dynamic_size(
            p_win=float(row.get("shadow_p_win", 0.5)),
            account_size=account_size, risk_per_trade_pct=risk_per_trade_pct,
            entry_price=float(row.get("entry", 0)),
            stop_price=float(row.get("stop", 0)),
            lot_size=lot_size, avg_win_r=avg_win_r, avg_loss_r=avg_loss_r,
            kelly_fraction_mult=kelly_fraction_mult, max_kelly_mult=max_kelly_mult,
        )
        results.append(sizing)
    sizing_df = pd.DataFrame(results, index=df.index)
    df["dyn_qty"] = sizing_df["qty"].astype(int)
    df["dyn_lots"] = sizing_df["lots"].astype(int)
    df["dyn_risk_idr"] = sizing_df["risk_idr"]
    df["kelly_mult"] = sizing_df["multiplier"]
    df["sizing_reason"] = sizing_df["sizing_reason"]
    return df
