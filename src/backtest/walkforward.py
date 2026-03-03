from __future__ import annotations

from typing import Iterable

import pandas as pd

from src.backtest.engine import BacktestCosts, evaluate_mode_backtest
from src.backtest.metrics import evaluate_strategy

MODE_HORIZON_DAYS = {
    "t1": 1,
    "swing": 10,
}


def _normalize_thresholds(values: Iterable[float] | None, fallback: list[float]) -> list[float]:
    raw = list(values) if values is not None else []
    if not raw:
        raw = fallback
    clean = sorted({float(v) for v in raw})
    if not clean:
        clean = fallback
    return clean


def _build_folds(
    unique_dates: list[pd.Timestamp],
    train_days: int,
    test_days: int,
    step_days: int,
) -> list[dict[str, pd.Timestamp]]:
    folds: list[dict[str, pd.Timestamp]] = []
    if train_days <= 0 or test_days <= 0:
        return folds

    total = len(unique_dates)
    required = train_days + test_days
    if total < required:
        return folds

    step = max(1, int(step_days))
    max_start = total - required
    for start_idx in range(0, max_start + 1, step):
        train_start = unique_dates[start_idx]
        train_end = unique_dates[start_idx + train_days - 1]
        test_start = unique_dates[start_idx + train_days]
        test_end = unique_dates[start_idx + train_days + test_days - 1]
        folds.append(
            {
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )
    return folds


def _objective(metrics: dict[str, float]) -> tuple[float, float, float, float]:
    return (
        float(metrics.get("ProfitFactor", 0.0)),
        float(metrics.get("Expectancy", 0.0)),
        float(metrics.get("MaxDD", 0.0)),
        float(metrics.get("Trades", 0.0)),
    )


def _pick_threshold_on_train(
    train_df: pd.DataFrame,
    mode: str,
    horizon_days: int,
    thresholds: list[float],
    costs: BacktestCosts,
    equity_allocation_pct: float,
    min_train_trades: int,
) -> tuple[float, dict[str, float]]:
    candidates: list[tuple[tuple[float, float, float, float], float, dict[str, float]]] = []

    for threshold in thresholds:
        metrics, _, _ = evaluate_mode_backtest(
            train_df,
            mode=mode,
            horizon_days=horizon_days,
            costs=costs,
            equity_allocation_pct=equity_allocation_pct,
            min_score=threshold,
        )
        if int(metrics.get("Trades", 0)) < min_train_trades:
            continue
        candidates.append((_objective(metrics), float(threshold), metrics))

    # Fallback: choose best threshold even when train trades are below target.
    if not candidates:
        for threshold in thresholds:
            metrics, _, _ = evaluate_mode_backtest(
                train_df,
                mode=mode,
                horizon_days=horizon_days,
                costs=costs,
                equity_allocation_pct=equity_allocation_pct,
                min_score=threshold,
            )
            if int(metrics.get("Trades", 0)) <= 0:
                continue
            candidates.append((_objective(metrics), float(threshold), metrics))

    if not candidates:
        return float(thresholds[0]), {"WinRate": 0.0, "ProfitFactor": 0.0, "Expectancy": 0.0, "Trades": 0, "CAGR": 0.0, "MaxDD": 0.0}

    best = sorted(candidates, key=lambda x: x[0], reverse=True)[0]
    return best[1], best[2]


def _aggregate_returns(returns: list[float], equity_allocation_pct: float) -> dict[str, float]:
    alloc_mult = max(0.0, float(equity_allocation_pct) / 100.0)
    if not returns:
        return evaluate_strategy(pd.Series([1.0]), [])

    equity = pd.Series(returns, dtype=float).mul(alloc_mult).add(1.0).cumprod()
    equity = pd.concat([pd.Series([1.0]), equity], ignore_index=True)
    return evaluate_strategy(equity, returns)


def run_walk_forward(
    scored_features: pd.DataFrame,
    costs: BacktestCosts,
    equity_allocation_pct: float = 100.0,
    train_days: int = 252,
    test_days: int = 63,
    step_days: int = 63,
    min_train_trades: int = 120,
    threshold_grid_t1: Iterable[float] | None = None,
    threshold_grid_swing: Iterable[float] | None = None,
) -> dict[str, object]:
    df = scored_features.copy()
    if df.empty:
        return {
            "config": {
                "train_days": train_days,
                "test_days": test_days,
                "step_days": step_days,
                "equity_allocation_pct": equity_allocation_pct,
                "min_train_trades": min_train_trades,
            },
            "n_folds": 0,
            "modes": {
                "t1": {"summary": evaluate_strategy(pd.Series([1.0]), []), "folds": [], "threshold_stats": {}},
                "swing": {"summary": evaluate_strategy(pd.Series([1.0]), []), "folds": [], "threshold_stats": {}},
            },
        }

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker", "close", "mode", "score"]).copy()
    df = df.sort_values(["date", "ticker"]).reset_index(drop=True)

    unique_dates = sorted(df["date"].drop_duplicates().tolist())
    folds = _build_folds(
        unique_dates=unique_dates,
        train_days=int(train_days),
        test_days=int(test_days),
        step_days=int(step_days),
    )

    t1_thresholds = _normalize_thresholds(threshold_grid_t1, [85.0, 90.0, 95.0, 97.0, 100.0])
    swing_thresholds = _normalize_thresholds(threshold_grid_swing, [55.0, 60.0, 65.0, 70.0, 75.0, 80.0])

    mode_payload: dict[str, object] = {}
    for mode in ["t1", "swing"]:
        horizon_days = MODE_HORIZON_DAYS[mode]
        thresholds = t1_thresholds if mode == "t1" else swing_thresholds
        fold_rows: list[dict[str, object]] = []
        selected_thresholds: list[float] = []
        all_oos_returns: list[float] = []

        for fold_idx, fold in enumerate(folds, start=1):
            train_df = df[(df["date"] >= fold["train_start"]) & (df["date"] <= fold["train_end"])].copy()
            test_df = df[(df["date"] >= fold["test_start"]) & (df["date"] <= fold["test_end"])].copy()

            selected_threshold, train_metrics = _pick_threshold_on_train(
                train_df=train_df,
                mode=mode,
                horizon_days=horizon_days,
                thresholds=thresholds,
                costs=costs,
                equity_allocation_pct=equity_allocation_pct,
                min_train_trades=min_train_trades,
            )
            oos_metrics, oos_returns, _ = evaluate_mode_backtest(
                test_df,
                mode=mode,
                horizon_days=horizon_days,
                costs=costs,
                equity_allocation_pct=equity_allocation_pct,
                min_score=selected_threshold,
            )
            all_oos_returns.extend(oos_returns)
            selected_thresholds.append(float(selected_threshold))
            fold_rows.append(
                {
                    "fold": fold_idx,
                    "train_start": pd.Timestamp(fold["train_start"]).strftime("%Y-%m-%d"),
                    "train_end": pd.Timestamp(fold["train_end"]).strftime("%Y-%m-%d"),
                    "test_start": pd.Timestamp(fold["test_start"]).strftime("%Y-%m-%d"),
                    "test_end": pd.Timestamp(fold["test_end"]).strftime("%Y-%m-%d"),
                    "selected_threshold": float(selected_threshold),
                    "train_metrics": train_metrics,
                    "oos_metrics": oos_metrics,
                }
            )

        summary = _aggregate_returns(all_oos_returns, equity_allocation_pct=equity_allocation_pct)
        threshold_stats: dict[str, float] = {}
        if selected_thresholds:
            s = pd.Series(selected_thresholds, dtype=float)
            threshold_stats = {
                "median": float(s.median()),
                "mean": float(s.mean()),
                "min": float(s.min()),
                "max": float(s.max()),
            }

        mode_payload[mode] = {
            "summary": summary,
            "folds": fold_rows,
            "threshold_stats": threshold_stats,
        }

    return {
        "config": {
            "train_days": int(train_days),
            "test_days": int(test_days),
            "step_days": int(step_days),
            "equity_allocation_pct": float(equity_allocation_pct),
            "min_train_trades": int(min_train_trades),
            "threshold_grid_t1": t1_thresholds,
            "threshold_grid_swing": swing_thresholds,
        },
        "n_folds": len(folds),
        "modes": mode_payload,
    }
