from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.backtest import (
    BacktestCosts,
    pass_live_gate,
    run_backtest,
    run_walk_forward,
    simulate_mode_trades,
)


def test_run_backtest_outputs_metrics():
    end = pd.Timestamp(datetime.utcnow().date())
    dates = pd.date_range(end=end, periods=30, freq="D")
    rows = []
    for i, d in enumerate(dates):
        close = 100 + i
        rows.append({"date": d, "ticker": "BBCA", "close": close, "mode": "t1", "score": 80})
        rows.append({"date": d, "ticker": "BBCA", "close": close, "mode": "swing", "score": 70})
    scored = pd.DataFrame(rows)

    out = run_backtest(scored, BacktestCosts())
    assert "t1" in out and "swing" in out
    for key in ["CAGR", "MaxDD", "WinRate", "ProfitFactor", "Expectancy", "Trades"]:
        assert key in out["t1"]


def test_pass_live_gate_thresholds():
    metrics = {"ProfitFactor": 1.3, "Expectancy": 0.1, "MaxDD": -10.0, "Trades": 200}
    assert pass_live_gate(metrics, profit_factor_min=1.2, expectancy_min=0.0, max_drawdown_pct_limit=15.0, min_trades=150)


def test_point_in_time_entry_filter_preserves_future_exit_bars():
    scored = pd.DataFrame(
        [
            {
                "date": "2026-01-05",
                "ticker": "AAAA",
                "close": 100.0,
                "mode": "t1",
                "score": 99.0,
                "universe_eligible": False,
            },
            {
                "date": "2026-01-06",
                "ticker": "AAAA",
                "close": 200.0,
                "mode": "t1",
                "score": 99.0,
                "universe_eligible": False,
            },
            {
                "date": "2026-01-05",
                "ticker": "BBBB",
                "close": 100.0,
                "mode": "t1",
                "score": 90.0,
                "universe_eligible": True,
            },
            {
                "date": "2026-01-06",
                "ticker": "BBBB",
                "close": 110.0,
                "mode": "t1",
                "score": 90.0,
                "universe_eligible": False,
            },
        ]
    )

    trades = simulate_mode_trades(
        scored_features=scored,
        mode="t1",
        horizon_days=1,
        costs=BacktestCosts(0.0, 0.0, 0.0),
        min_score=80.0,
    )

    assert len(trades) == 1
    assert trades.iloc[0]["ticker"] == "BBBB"
    assert trades.iloc[0]["exit"] == 110.0
    assert round(float(trades.iloc[0]["return"]), 6) == 0.1


def test_walk_forward_builds_folds_from_eligible_dates_only():
    ineligible_dates = pd.date_range("2025-12-01", periods=20, freq="D")
    eligible_dates = pd.date_range("2026-01-01", periods=17, freq="D")
    rows = []
    for index, date in enumerate([*ineligible_dates, *eligible_dates]):
        is_eligible = date in eligible_dates
        for mode in ["t1", "swing"]:
            rows.append(
                {
                    "date": date,
                    "ticker": "BBCA",
                    "close": 100.0 + index,
                    "mode": mode,
                    "score": 99.0,
                    "universe_eligible": is_eligible,
                }
            )

    result = run_walk_forward(
        pd.DataFrame(rows),
        BacktestCosts(0.0, 0.0, 0.0),
        train_days=3,
        test_days=2,
        step_days=2,
        min_train_trades=1,
        threshold_grid_t1=[80.0],
        threshold_grid_swing=[80.0],
    )

    assert result["n_folds"] == 2
    assert result["modes"]["t1"]["folds"][0]["train_start"] == "2026-01-01"
    assert result["modes"]["swing"]["folds"][0]["train_start"] == "2026-01-01"
