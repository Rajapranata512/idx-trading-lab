from __future__ import annotations

from typing import Iterable

import pandas as pd

from src.backtest.engine import BacktestCosts, evaluate_mode_backtest
from src.backtest.metrics import evaluate_strategy
from src.config import Settings
from src.runtime import regime_bucket_from_features

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
    purge_days: int = 0,
) -> list[dict[str, pd.Timestamp]]:
    """Build walk-forward folds with optional purge (embargo) window.

    The purge window inserts a gap of *purge_days* between the end of the
    training set and the start of the test set.  This prevents label leakage
    when labels depend on forward returns that overlap with late-training rows.
    """
    folds: list[dict[str, pd.Timestamp]] = []
    if train_days <= 0 or test_days <= 0:
        return folds

    total = len(unique_dates)
    required = train_days + purge_days + test_days
    if total < required:
        return folds

    step = max(1, int(step_days))
    max_start = total - required
    for start_idx in range(0, max_start + 1, step):
        train_start = unique_dates[start_idx]
        train_end = unique_dates[start_idx + train_days - 1]
        # Skip purge_days after train_end
        test_start_idx = start_idx + train_days + purge_days
        test_end_idx = test_start_idx + test_days - 1
        if test_end_idx >= total:
            break
        test_start = unique_dates[test_start_idx]
        test_end = unique_dates[test_end_idx]
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


def _regime_threshold_summary(fold_rows: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    buckets: dict[str, list[float]] = {"risk_on": [], "risk_off": []}
    for row in fold_rows:
        thresholds = row.get("regime_thresholds", {})
        if not isinstance(thresholds, dict):
            continue
        for regime, payload in thresholds.items():
            if regime not in buckets or not isinstance(payload, dict):
                continue
            try:
                buckets[regime].append(float(payload.get("threshold")))
            except (TypeError, ValueError):
                continue

    summary: dict[str, dict[str, float]] = {}
    for regime, values in buckets.items():
        if not values:
            continue
        series = pd.Series(values, dtype=float)
        summary[regime] = {
            "median": float(series.median()),
            "mean": float(series.mean()),
            "min": float(series.min()),
            "max": float(series.max()),
            "count": int(series.count()),
        }
    return summary


def _fold_stability(fold_rows: list[dict[str, object]]) -> dict[str, float]:
    if not fold_rows:
        return {}
    threshold_values = []
    expectancy_values = []
    pf_values = []
    for row in fold_rows:
        try:
            threshold_values.append(float(row.get("selected_threshold")))
        except (TypeError, ValueError):
            pass
        oos_metrics = row.get("oos_metrics", {})
        if isinstance(oos_metrics, dict):
            expectancy_values.append(float(oos_metrics.get("Expectancy", 0.0)))
            pf_values.append(float(oos_metrics.get("ProfitFactor", 0.0)))

    payload: dict[str, float] = {}
    if threshold_values:
        s = pd.Series(threshold_values, dtype=float)
        payload["threshold_std"] = round(float(s.std(ddof=0)), 6)
        payload["threshold_range"] = round(float(s.max() - s.min()), 6)
    if expectancy_values:
        s = pd.Series(expectancy_values, dtype=float)
        payload["oos_expectancy_std"] = round(float(s.std(ddof=0)), 6)
    if pf_values:
        s = pd.Series(pf_values, dtype=float)
        payload["oos_profit_factor_std"] = round(float(s.std(ddof=0)), 6)
    return payload


def _pick_regime_thresholds_on_train(
    train_df: pd.DataFrame,
    mode: str,
    horizon_days: int,
    thresholds: list[float],
    costs: BacktestCosts,
    equity_allocation_pct: float,
    min_train_trades: int,
    settings: Settings | None,
) -> dict[str, dict[str, object]]:
    if str(mode).lower() != "swing" or settings is None or train_df.empty:
        return {}
    work = train_df.copy()
    work["regime_bucket"] = regime_bucket_from_features(work, settings=settings, default="risk_off")
    out: dict[str, dict[str, object]] = {}
    for regime in ["risk_on", "risk_off"]:
        subset = work[work["regime_bucket"] == regime].copy()
        if subset.empty:
            continue
        threshold, metrics = _pick_threshold_on_train(
            train_df=subset,
            mode=mode,
            horizon_days=horizon_days,
            thresholds=thresholds,
            costs=costs,
            equity_allocation_pct=equity_allocation_pct,
            min_train_trades=max(10, int(min_train_trades) // 2),
        )
        out[regime] = {
            "threshold": float(threshold),
            "train_rows": int(len(subset)),
            "train_metrics": metrics,
        }
    return out


def _evaluate_regime_thresholds_oos(
    test_df: pd.DataFrame,
    mode: str,
    horizon_days: int,
    regime_thresholds: dict[str, dict[str, object]],
    costs: BacktestCosts,
    equity_allocation_pct: float,
    settings: Settings | None,
) -> tuple[dict[str, float], dict[str, dict[str, object]]]:
    if not regime_thresholds or settings is None or test_df.empty:
        return evaluate_strategy(pd.Series([1.0]), []), {}

    work = test_df.copy()
    work["regime_bucket"] = regime_bucket_from_features(work, settings=settings, default="risk_off")
    oos_returns: list[float] = []
    breakdown: dict[str, dict[str, object]] = {}
    for regime, payload in regime_thresholds.items():
        if not isinstance(payload, dict):
            continue
        threshold = float(payload.get("threshold", 0.0))
        subset = work[work["regime_bucket"] == regime].copy()
        if subset.empty:
            continue
        metrics, returns, _ = evaluate_mode_backtest(
            subset,
            mode=mode,
            horizon_days=horizon_days,
            costs=costs,
            equity_allocation_pct=equity_allocation_pct,
            min_score=threshold,
        )
        oos_returns.extend(returns)
        breakdown[regime] = {
            "threshold": threshold,
            "rows": int(len(subset)),
            "oos_metrics": metrics,
        }

    summary = _aggregate_returns(oos_returns, equity_allocation_pct=equity_allocation_pct)
    return summary, breakdown


def run_walk_forward(
    scored_features: pd.DataFrame,
    costs: BacktestCosts,
    settings: Settings | None = None,
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
        purge_days=max(MODE_HORIZON_DAYS.values()),  # anti-leakage embargo
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
            regime_thresholds = _pick_regime_thresholds_on_train(
                train_df=train_df,
                mode=mode,
                horizon_days=horizon_days,
                thresholds=thresholds,
                costs=costs,
                equity_allocation_pct=equity_allocation_pct,
                min_train_trades=min_train_trades,
                settings=settings,
            )
            oos_metrics, oos_returns, _ = evaluate_mode_backtest(
                test_df,
                mode=mode,
                horizon_days=horizon_days,
                costs=costs,
                equity_allocation_pct=equity_allocation_pct,
                min_score=selected_threshold,
            )
            regime_aware_summary, regime_aware_breakdown = _evaluate_regime_thresholds_oos(
                test_df=test_df,
                mode=mode,
                horizon_days=horizon_days,
                regime_thresholds=regime_thresholds,
                costs=costs,
                equity_allocation_pct=equity_allocation_pct,
                settings=settings,
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
                    "regime_thresholds": regime_thresholds,
                    "oos_regime_aware_metrics": regime_aware_summary,
                    "oos_regime_breakdown": regime_aware_breakdown,
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
            "regime_threshold_stats": _regime_threshold_summary(fold_rows),
            "stability": _fold_stability(fold_rows),
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
