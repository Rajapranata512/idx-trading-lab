from __future__ import annotations

import numpy as np
import pandas as pd


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    running_peak = equity_curve.cummax()
    drawdown = (equity_curve - running_peak) / (running_peak + 1e-9)
    return float(drawdown.min()) * 100.0


def compute_cagr(equity_curve: pd.Series, periods_per_year: int = 252) -> float:
    if len(equity_curve) < 2:
        return 0.0
    start = float(equity_curve.iloc[0])
    end = float(equity_curve.iloc[-1])
    if start <= 0 or end <= 0:
        return 0.0
    years = len(equity_curve) / periods_per_year
    if years <= 0:
        return 0.0
    return ((end / start) ** (1 / years) - 1) * 100.0


def summarize_trade_returns(returns: list[float]) -> dict[str, float]:
    if not returns:
        return {
            "WinRate": 0.0,
            "ProfitFactor": 0.0,
            "Expectancy": 0.0,
            "Trades": 0,
        }

    r = np.array(returns, dtype=float)
    wins = r[r > 0]
    losses = r[r < 0]
    win_rate = float((r > 0).mean()) * 100.0
    gross_profit = float(wins.sum()) if wins.size else 0.0
    gross_loss = float(-losses.sum()) if losses.size else 0.0
    profit_factor = gross_profit / (gross_loss + 1e-9)
    expectancy = float(r.mean())
    return {
        "WinRate": win_rate,
        "ProfitFactor": profit_factor,
        "Expectancy": expectancy,
        "Trades": int(r.size),
    }


def evaluate_strategy(equity_curve: pd.Series, returns: list[float]) -> dict[str, float]:
    metrics = summarize_trade_returns(returns)
    metrics["CAGR"] = compute_cagr(equity_curve)
    metrics["MaxDD"] = compute_max_drawdown(equity_curve)
    return metrics
