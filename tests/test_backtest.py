from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.backtest import BacktestCosts, pass_live_gate, run_backtest


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
