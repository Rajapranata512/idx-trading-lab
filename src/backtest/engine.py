from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.backtest.metrics import evaluate_strategy


@dataclass(frozen=True)
class BacktestCosts:
    buy_fee_pct: float = 0.15
    sell_fee_pct: float = 0.25
    slippage_pct: float = 0.10


def _pct_to_mult(pct: float) -> float:
    return pct / 100.0


def _prepare_latest(features: pd.DataFrame) -> pd.DataFrame:
    out = features.copy()
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
    return out


def _simulate_horizon_returns(
    features: pd.DataFrame,
    horizon_days: int,
    score_col: str,
    mode_col: str,
    mode_value: str,
    costs: BacktestCosts,
    equity_allocation_pct: float = 100.0,
    min_score: float | None = None,
) -> tuple[list[float], pd.Series]:
    df = _prepare_latest(features)

    # Compute forward close from unique ticker/date bars to avoid horizon distortion
    # when scored features contain multiple rows per bar (e.g. different modes).
    bars = df.sort_values(["ticker", "date"]).drop_duplicates(subset=["ticker", "date"], keep="first").copy()
    bars["fwd_close"] = bars.groupby("ticker")["close"].shift(-horizon_days)
    df = df.merge(bars[["ticker", "date", "fwd_close"]], on=["ticker", "date"], how="left")

    score_df = df[df[mode_col] == mode_value].copy()
    if min_score is not None and score_col in score_df.columns:
        score_df = score_df[score_df[score_col] >= float(min_score)].copy()
    score_df = score_df.sort_values(["date", score_col], ascending=[True, False])
    score_df = score_df.groupby("date").head(1).copy()
    score_df = score_df.dropna(subset=["close", "fwd_close"])
    if score_df.empty:
        return [], pd.Series([1.0])

    buy_cost = _pct_to_mult(costs.buy_fee_pct + costs.slippage_pct)
    sell_cost = _pct_to_mult(costs.sell_fee_pct + costs.slippage_pct)

    entry = score_df["close"] * (1.0 + buy_cost)
    exit_ = score_df["fwd_close"] * (1.0 - sell_cost)
    trade_returns = ((exit_ - entry) / (entry + 1e-9)).astype(float).tolist()

    alloc_mult = max(0.0, float(equity_allocation_pct) / 100.0)
    equity_returns = pd.Series(trade_returns).astype(float) * alloc_mult
    equity = equity_returns.add(1.0).cumprod()
    equity.index = range(len(equity))
    equity = pd.concat([pd.Series([1.0]), equity], ignore_index=True)
    return trade_returns, equity


def simulate_mode_trades(
    scored_features: pd.DataFrame,
    mode: str,
    horizon_days: int,
    costs: BacktestCosts,
    min_score: float | None = None,
) -> pd.DataFrame:
    """Simulate one top-ranked trade per day and return trade-level rows."""
    df = _prepare_latest(scored_features)
    bars = df.sort_values(["ticker", "date"]).drop_duplicates(subset=["ticker", "date"], keep="first").copy()
    bars["fwd_close"] = bars.groupby("ticker")["close"].shift(-horizon_days)
    df = df.merge(bars[["ticker", "date", "fwd_close"]], on=["ticker", "date"], how="left")

    trades = df[df["mode"] == mode].copy()
    if min_score is not None and "score" in trades.columns:
        trades = trades[trades["score"] >= float(min_score)].copy()
    trades = trades.sort_values(["date", "score"], ascending=[True, False])
    trades = trades.groupby("date").head(1).copy()
    trades = trades.dropna(subset=["close", "fwd_close"])
    if trades.empty:
        return pd.DataFrame(columns=["date", "ticker", "mode", "score", "entry", "exit", "return"])

    buy_cost = _pct_to_mult(costs.buy_fee_pct + costs.slippage_pct)
    sell_cost = _pct_to_mult(costs.sell_fee_pct + costs.slippage_pct)

    trades["entry"] = trades["close"] * (1.0 + buy_cost)
    trades["exit"] = trades["fwd_close"] * (1.0 - sell_cost)
    trades["return"] = ((trades["exit"] - trades["entry"]) / (trades["entry"] + 1e-9)).astype(float)
    trades = trades[["date", "ticker", "mode", "score", "entry", "exit", "return"]].copy()
    return trades.sort_values("date").reset_index(drop=True)


def evaluate_mode_backtest(
    scored_features: pd.DataFrame,
    mode: str,
    horizon_days: int,
    costs: BacktestCosts,
    equity_allocation_pct: float = 100.0,
    min_score: float | None = None,
) -> tuple[dict[str, float], list[float], pd.Series]:
    trades = simulate_mode_trades(
        scored_features=scored_features,
        mode=mode,
        horizon_days=horizon_days,
        costs=costs,
        min_score=min_score,
    )
    returns = trades["return"].astype(float).tolist() if not trades.empty else []
    alloc_mult = max(0.0, float(equity_allocation_pct) / 100.0)
    equity = pd.Series(returns, dtype=float).mul(alloc_mult).add(1.0).cumprod()
    equity = pd.concat([pd.Series([1.0]), equity], ignore_index=True)
    metrics = evaluate_strategy(equity, returns)
    return metrics, returns, equity


def run_backtest(
    scored_features: pd.DataFrame,
    costs: BacktestCosts,
    equity_allocation_pct: float = 100.0,
) -> dict[str, dict[str, float]]:
    """Run bar-based backtest for T+1 and Swing modes."""
    t1_metrics, _, _ = evaluate_mode_backtest(
        scored_features,
        mode="t1",
        horizon_days=1,
        costs=costs,
        equity_allocation_pct=equity_allocation_pct,
    )
    sw_metrics, _, _ = evaluate_mode_backtest(
        scored_features,
        mode="swing",
        horizon_days=10,
        costs=costs,
        equity_allocation_pct=equity_allocation_pct,
    )
    return {
        "t1": t1_metrics,
        "swing": sw_metrics,
    }


def pass_live_gate(
    metrics: dict[str, float],
    profit_factor_min: float,
    expectancy_min: float,
    max_drawdown_pct_limit: float,
    min_trades: int,
) -> bool:
    return bool(
        metrics.get("ProfitFactor", 0.0) >= profit_factor_min
        and metrics.get("Expectancy", 0.0) > expectancy_min
        and abs(metrics.get("MaxDD", 0.0)) <= max_drawdown_pct_limit
        and metrics.get("Trades", 0) >= min_trades
    )
