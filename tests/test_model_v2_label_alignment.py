from __future__ import annotations

import pandas as pd

from src.config import load_settings
from src.model_v2.labeling import build_training_dataset, simulate_trade_outcomes
from src.model_v2.train import _prepare_training_frame
from src.strategy.ranker import score_history_modes


def _two_bar_frame(**second_bar: float) -> pd.DataFrame:
    rows = [
        {
            "date": "2026-01-05",
            "ticker": "AAA",
            "open": 100.0,
            "high": 103.0,
            "low": 97.0,
            "close": 100.0,
            "volume": 1_000_000,
            "atr_14": 5.0,
        },
        {
            "date": "2026-01-06",
            "ticker": "AAA",
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 101.0,
            "volume": 1_000_000,
            "atr_14": 5.0,
            **second_bar,
        },
    ]
    return pd.DataFrame(rows)


def test_ambiguous_intrabar_is_conservative_stop_first() -> None:
    bars = _two_bar_frame(open=100.0, high=111.0, low=89.0, close=105.0)
    result = simulate_trade_outcomes(
        bars,
        mode="t1",
        horizon_days=1,
        stop_atr_mult=2.0,
        tp1_r_mult=1.0,
        roundtrip_cost_pct=0.0,
    )
    trade = result.dropna(subset=["y_cls"]).iloc[0]
    assert trade["outcome"] == "stop_hit"
    assert bool(trade["ambiguous_intrabar"]) is True
    assert trade["exit_price"] == 90.0
    assert trade["y_cls"] == 0


def test_gap_outside_plan_is_rejected_before_entry() -> None:
    bars = _two_bar_frame(open=85.0, high=95.0, low=84.0, close=92.0)
    result = simulate_trade_outcomes(
        bars,
        mode="t1",
        horizon_days=1,
        stop_atr_mult=2.0,
        tp1_r_mult=1.0,
        roundtrip_cost_pct=0.0,
    )
    trade = result[result["outcome"].eq("entry_rejected_gap")].iloc[0]
    assert bool(trade["entry_eligible"]) is False
    assert trade["entry_price"] == 85.0
    assert pd.isna(trade["y_cls"])
    assert pd.isna(trade["y_reg"])


def test_candidate_aligned_dataset_matches_score_floor_and_top_n() -> None:
    rows: list[dict[str, object]] = []
    scores = {"AAA": 99.0, "BBB": 95.0, "CCC": 85.0, "DDD": 70.0}
    for day in range(4):
        for offset, (ticker, score) in enumerate(scores.items()):
            close = 100.0 + day + offset
            rows.append(
                {
                    "date": pd.Timestamp("2026-01-05") + pd.Timedelta(days=day),
                    "ticker": ticker,
                    "mode": "t1",
                    "score": score,
                    "open": close,
                    "high": close + 2.0,
                    "low": close - 2.0,
                    "close": close,
                    "volume": 1_000_000,
                    "atr_14": 5.0,
                }
            )

    dataset = build_training_dataset(
        pd.DataFrame(rows),
        mode="t1",
        horizon_days=1,
        candidate_alignment_enabled=True,
        min_live_score=90.0,
        top_n_per_date=2,
        roundtrip_cost_pct=0.0,
    )

    assert set(dataset["ticker"]) == {"AAA", "BBB"}
    assert dataset["score"].ge(90.0).all()
    assert dataset["candidate_rank"].le(2).all()
    assert dataset["candidate_aligned"].all()
    assert dataset["label_strategy"].eq(
        "first_touch_stop_tp_with_net_horizon_exit"
    ).all()


def _historical_score_frame(include_future: bool) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = [pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06")]
    if include_future:
        dates.append(pd.Timestamp("2026-01-07"))
    for day_index, date in enumerate(dates):
        for ticker_index, ticker in enumerate(["AAA", "BBB", "CCC", "DDD"]):
            future_scale = 100.0 if day_index == 2 else 1.0
            close = 100.0 + ticker_index + day_index
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "open": close,
                    "high": close + 2.0,
                    "low": close - 2.0,
                    "close": close,
                    "volume": 1_000_000,
                    "avg_vol_20d": 1_000_000.0,
                    "ma_20": close - 1.0,
                    "ma_50": close - 2.0,
                    "ret_5d": (0.01 + ticker_index * 0.01) * future_scale,
                    "ret_20d": (0.02 + ticker_index * 0.01) * future_scale,
                    "relative_ret_20d": (0.01 + ticker_index * 0.005) * future_scale,
                    "vol_20d": (0.02 + ticker_index * 0.01) * future_scale,
                    "atr_pct": 2.0 + ticker_index,
                }
            )
    return pd.DataFrame(rows)


def test_future_cross_section_does_not_change_historical_scores() -> None:
    base = score_history_modes(_historical_score_frame(False), min_avg_volume_20d=100)
    extended = score_history_modes(_historical_score_frame(True), min_avg_volume_20d=100)
    cutoff = pd.Timestamp("2026-01-06")
    columns = ["date", "ticker", "mode", "score"]
    left = base[base["date"].le(cutoff)][columns].sort_values(columns[:3]).reset_index(drop=True)
    right = extended[extended["date"].le(cutoff)][columns].sort_values(columns[:3]).reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right)


def test_swing_training_preserves_first_touch_target() -> None:
    settings = load_settings("config/settings.json")
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=4),
            "ticker": ["AAA", "BBB", "CCC", "DDD"],
            "y": [1, 0, 1, 0],
            "net_return": [-0.5, 1.0, -0.25, 0.75],
            "label_strategy": [
                "first_touch_stop_tp_with_net_horizon_exit"
            ] * 4,
        }
    )
    prepared = _prepare_training_frame(frame, mode="swing", settings=settings)
    assert prepared["y"].tolist() == [1, 0, 1, 0]
    assert prepared["label_strategy"].nunique() == 1
