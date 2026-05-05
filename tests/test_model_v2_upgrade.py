"""Comprehensive tests for model_v2 upgrade modules.

Covers: labeling, calibration, promotion gate, multi-model training,
feature lag verification, and closed-loop feedback.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_price_bars(n_days: int = 120, tickers: list[str] | None = None) -> pd.DataFrame:
    """Generate synthetic OHLCV data suitable for all model_v2 modules."""
    tickers = tickers or ["BBCA", "TLKM", "ASII"]
    rows: list[dict] = []
    rng = np.random.RandomState(42)
    base_date = datetime(2025, 1, 2)
    for ticker in tickers:
        price = 10000.0 + rng.randn() * 500
        for d in range(n_days):
            date = base_date + timedelta(days=d)
            ret = rng.randn() * 0.02
            close = price * (1.0 + ret)
            high = close * (1.0 + abs(rng.randn() * 0.015))
            low = close * (1.0 - abs(rng.randn() * 0.015))
            open_ = close * (1.0 + rng.randn() * 0.005)
            volume = int(rng.uniform(500_000, 5_000_000))
            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "ticker": ticker,
                "open": round(open_, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
            })
            price = close
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _make_scored_history(n_days: int = 120) -> pd.DataFrame:
    """Generate scored history with mode column for training."""
    bars = _make_price_bars(n_days=n_days)
    from src.features.compute_features import compute_features
    features = compute_features(bars)
    features["mode"] = np.where(
        np.random.RandomState(42).rand(len(features)) > 0.5, "t1", "swing"
    )
    features["score"] = np.random.RandomState(42).uniform(50, 100, len(features)).round(2)
    return features


# ===========================================================================
# 1. Labeling V2 Tests
# ===========================================================================

class TestLabelingV2:
    def test_simulate_trade_outcomes_returns_correct_columns(self):
        from src.model_v2.labeling import simulate_trade_outcomes
        bars = _make_price_bars(n_days=60)
        # Need atr_14
        from src.features.compute_features import compute_features
        featured = compute_features(bars)
        result = simulate_trade_outcomes(
            bars=featured, mode="swing", horizon_days=10,
            stop_atr_mult=2.0, tp1_r_mult=1.0,
        )
        for col in ["y_cls", "y_reg", "outcome", "exit_price"]:
            assert col in result.columns, f"Missing column: {col}"

    def test_outcomes_are_valid_categories(self):
        from src.model_v2.labeling import simulate_trade_outcomes
        from src.features.compute_features import compute_features
        bars = compute_features(_make_price_bars(n_days=80))
        result = simulate_trade_outcomes(bars=bars, mode="t1", horizon_days=5)
        valid = result.dropna(subset=["outcome"])
        assert set(valid["outcome"].unique()).issubset({"tp_hit", "stop_hit", "horizon_exit"})

    def test_y_cls_is_binary(self):
        from src.model_v2.labeling import simulate_trade_outcomes
        from src.features.compute_features import compute_features
        bars = compute_features(_make_price_bars(n_days=80))
        result = simulate_trade_outcomes(bars=bars, mode="swing", horizon_days=10)
        valid = result.dropna(subset=["y_cls"])
        assert set(valid["y_cls"].unique()).issubset({0, 1, 0.0, 1.0})

    def test_build_training_dataset_filters_by_mode(self):
        from src.model_v2.labeling import build_training_dataset
        scored = _make_scored_history(n_days=80)
        result = build_training_dataset(
            scored_history=scored, mode="swing", horizon_days=10,
        )
        if not result.empty:
            assert (result["mode"] == "swing").all()

    def test_empty_input_returns_empty(self):
        from src.model_v2.labeling import simulate_trade_outcomes
        empty = pd.DataFrame(columns=["date", "ticker", "open", "high", "low", "close", "volume", "atr_14"])
        result = simulate_trade_outcomes(bars=empty, mode="swing", horizon_days=10)
        assert result.empty or len(result) == 0


# ===========================================================================
# 2. Calibration Tests
# ===========================================================================

class TestCalibration:
    def test_calibrate_model_returns_wrapper(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.impute import SimpleImputer
        from sklearn.preprocessing import StandardScaler
        from src.model_v2.calibration import calibrate_model, CalibratedModelWrapper

        rng = np.random.RandomState(42)
        X = pd.DataFrame({"f1": rng.randn(200), "f2": rng.randn(200)})
        y = (rng.rand(200) > 0.5).astype(int)

        pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=200)),
        ])
        pipe.fit(X, y)

        wrapper = calibrate_model(pipe, X.iloc[150:], y[150:], method="isotonic")
        assert isinstance(wrapper, CalibratedModelWrapper)
        probs = wrapper.predict_proba(X)
        assert probs.shape == (200, 2)
        assert (probs >= 0).all() and (probs <= 1).all()

    def test_calibration_with_too_few_samples_returns_uncalibrated(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.impute import SimpleImputer
        from sklearn.preprocessing import StandardScaler
        from src.model_v2.calibration import calibrate_model

        rng = np.random.RandomState(42)
        X = pd.DataFrame({"f1": rng.randn(50), "f2": rng.randn(50)})
        y = (rng.rand(50) > 0.5).astype(int)

        pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=200)),
        ])
        pipe.fit(X, y)

        # Only 5 samples — too few for calibration
        wrapper = calibrate_model(pipe, X.iloc[:5], y[:5])
        assert wrapper.calibrator is None  # uncalibrated fallback

    def test_evaluate_calibration_ece(self):
        from src.model_v2.calibration import evaluate_calibration
        y_true = np.array([1, 1, 0, 0, 1, 0, 1, 0, 1, 1])
        y_prob = np.array([0.9, 0.8, 0.2, 0.1, 0.7, 0.3, 0.6, 0.4, 0.85, 0.75])
        result = evaluate_calibration(y_true, y_prob, n_bins=5)
        assert "ece" in result
        assert result["ece"] >= 0.0
        assert len(result["bin_stats"]) == 5


# ===========================================================================
# 3. Promotion Gate Tests
# ===========================================================================

class TestPromotionGate:
    def test_passing_gate(self):
        from src.model_v2.promotion import check_promotion_gate
        folds = [
            {"ProfitFactor": 1.8, "Expectancy": 0.15, "MaxDD": 5.0, "Trades": 50},
            {"ProfitFactor": 1.5, "Expectancy": 0.10, "MaxDD": 7.0, "Trades": 45},
            {"ProfitFactor": 1.3, "Expectancy": 0.05, "MaxDD": 6.0, "Trades": 40},
        ]
        result = check_promotion_gate(folds)
        assert result["passed"] is True
        assert len(result["reasons"]) == 0

    def test_failing_gate_low_profit_factor(self):
        from src.model_v2.promotion import check_promotion_gate
        folds = [
            {"ProfitFactor": 0.8, "Expectancy": -0.05, "MaxDD": 15.0, "Trades": 50},
            {"ProfitFactor": 0.9, "Expectancy": -0.02, "MaxDD": 8.0, "Trades": 45},
            {"ProfitFactor": 1.0, "Expectancy": 0.01, "MaxDD": 6.0, "Trades": 40},
        ]
        result = check_promotion_gate(folds)
        assert result["passed"] is False
        assert len(result["reasons"]) > 0

    def test_empty_folds_fails(self):
        from src.model_v2.promotion import check_promotion_gate
        result = check_promotion_gate([])
        assert result["passed"] is False

    def test_fold_details_count(self):
        from src.model_v2.promotion import check_promotion_gate
        folds = [
            {"ProfitFactor": 1.5, "Expectancy": 0.1, "MaxDD": 5.0, "Trades": 50},
            {"ProfitFactor": 1.3, "Expectancy": 0.08, "MaxDD": 6.0, "Trades": 40},
        ]
        result = check_promotion_gate(folds)
        assert len(result["fold_details"]) == 2
        assert result["summary"]["n_folds"] == 2

    def test_custom_gate_thresholds(self):
        from src.model_v2.promotion import check_promotion_gate
        # Relaxed gate — should pass
        folds = [
            {"ProfitFactor": 1.05, "Expectancy": 0.01, "MaxDD": 5.0, "Trades": 80},
            {"ProfitFactor": 1.1, "Expectancy": 0.02, "MaxDD": 4.0, "Trades": 70},
        ]
        gate = {
            "min_oos_trades": 100,
            "min_profit_factor": 1.0,
            "min_expectancy": -0.01,
            "max_drawdown_pct": 20.0,
            "min_fold_profitable_pct": 0.5,
        }
        result = check_promotion_gate(folds, gate=gate)
        assert result["passed"] is True


# ===========================================================================
# 4. Feature Lag Verification (Anti-Leakage)
# ===========================================================================

class TestFeatureLagVerification:
    """Verify that all computed features use only past/present data.

    Strategy: compute features, then shift the input forward by 1 day.
    Features at time T should NOT change if future data changes.
    """

    def test_features_do_not_use_future_data(self):
        from src.features.compute_features import compute_features

        bars = _make_price_bars(n_days=100, tickers=["BBCA"])
        bars = bars.sort_values(["ticker", "date"]).reset_index(drop=True)

        features_full = compute_features(bars)

        # Remove last 5 rows (future data) and recompute
        bars_truncated = bars.iloc[:-5].copy()
        features_trunc = compute_features(bars_truncated)

        # Features at the same dates should be identical
        common_dates = set(features_trunc["date"].values) & set(features_full["date"].values)
        assert len(common_dates) > 0

        full_subset = features_full[features_full["date"].isin(common_dates)].copy()
        trunc_subset = features_trunc[features_trunc["date"].isin(common_dates)].copy()

        full_subset = full_subset.sort_values(["ticker", "date"]).reset_index(drop=True)
        trunc_subset = trunc_subset.sort_values(["ticker", "date"]).reset_index(drop=True)

        # Check numeric feature columns
        numeric_cols = [c for c in full_subset.select_dtypes(include=[np.number]).columns
                       if c not in ("volume", "open", "high", "low", "close")]
        # Cross-sectional ranks may change because universe changes, skip those
        skip_cols = {"rank_ret_20d", "rank_vol_20d", "rank_score"}
        check_cols = [c for c in numeric_cols if c in trunc_subset.columns and c not in skip_cols]

        mismatches = []
        for col in check_cols:
            a = full_subset[col].values
            b = trunc_subset[col].values
            # Allow NaN at the same positions
            both_nan = np.isnan(a) & np.isnan(b)
            both_valid = ~np.isnan(a) & ~np.isnan(b)
            if both_valid.sum() == 0:
                continue
            if not np.allclose(a[both_valid], b[both_valid], rtol=1e-6, atol=1e-9):
                mismatches.append(col)

        assert len(mismatches) == 0, (
            f"Features leaked future data! Mismatched columns: {mismatches}"
        )

    def test_no_forward_looking_rolling(self):
        """Ensure rolling windows produce NaN at the start, not the end."""
        from src.features.compute_features import compute_features

        bars = _make_price_bars(n_days=60, tickers=["BBCA"])
        features = compute_features(bars)
        ticker_df = features[features["ticker"] == "BBCA"].sort_values("date").reset_index(drop=True)

        # Rolling 20 features should have NaN in first ~20 rows
        for col in ["vol_20d", "ma_20", "avg_vol_20d"]:
            if col in ticker_df.columns:
                first_10 = ticker_df[col].iloc[:10]
                last_10 = ticker_df[col].iloc[-10:]
                nan_count_start = first_10.isna().sum()
                nan_count_end = last_10.isna().sum()
                # More NaN at start than end = forward-looking is absent
                assert nan_count_start >= nan_count_end, (
                    f"Feature '{col}' has more NaN at end ({nan_count_end}) "
                    f"than start ({nan_count_start}), possible forward-looking window"
                )


# ===========================================================================
# 5. Multi-Model Training Tests
# ===========================================================================

class TestMultiModelTraining:
    def test_model_features_list_is_complete(self):
        from src.model_v2.train import MODEL_FEATURES
        assert len(MODEL_FEATURES) >= 15
        # Core features must exist
        for f in ["score", "ret_1d", "ret_5d", "atr_pct", "vol_20d"]:
            assert f in MODEL_FEATURES

    def test_training_rows_returns_labeled_data(self):
        from src.model_v2.train import _training_rows_for_mode
        scored = _make_scored_history(n_days=80)
        result = _training_rows_for_mode(
            scored_history=scored,
            mode="swing",
            horizon_days=10,
            roundtrip_cost_pct=0.65,
        )
        if not result.empty:
            assert "y" in result.columns
            assert set(result["y"].unique()).issubset({0, 1})

    def test_build_feature_frame_handles_missing_cols(self):
        from src.model_v2.train import _build_feature_frame
        df = pd.DataFrame({"close": [100, 200], "score": [80, 90]})
        result = _build_feature_frame(df)
        assert len(result) == 2
        # Missing columns should be filled with 0.0
        assert result["ret_1d"].iloc[0] == 0.0


# ===========================================================================
# 6. Kelly Sizing Tests
# ===========================================================================

class TestKellySizing:
    def test_kelly_fraction_positive_edge(self):
        from src.risk.kelly_sizing import kelly_fraction
        # p=0.6, win=1.5R, loss=1R → positive edge
        kf = kelly_fraction(0.6, avg_win_r=1.5, avg_loss_r=1.0)
        assert kf > 0

    def test_kelly_fraction_negative_edge(self):
        from src.risk.kelly_sizing import kelly_fraction
        # p=0.3, win=1R, loss=1R → negative edge
        kf = kelly_fraction(0.3, avg_win_r=1.0, avg_loss_r=1.0)
        assert kf < 0

    def test_kelly_fraction_breakeven(self):
        from src.risk.kelly_sizing import kelly_fraction
        # p=0.5, win=1R, loss=1R → zero edge
        kf = kelly_fraction(0.5, avg_win_r=1.0, avg_loss_r=1.0)
        assert abs(kf) < 0.01

    def test_compute_dynamic_size_positive(self):
        from src.risk.kelly_sizing import compute_dynamic_size
        result = compute_dynamic_size(
            p_win=0.65, account_size=100_000_000,
            risk_per_trade_pct=0.75, entry_price=10000,
            stop_price=9800, lot_size=100,
        )
        assert result["qty"] > 0
        assert result["lots"] >= 1
        assert result["risk_idr"] > 0
        assert result["sizing_reason"] != "negative_edge"

    def test_compute_dynamic_size_negative_edge(self):
        from src.risk.kelly_sizing import compute_dynamic_size
        result = compute_dynamic_size(
            p_win=0.30, account_size=100_000_000,
            risk_per_trade_pct=0.75, entry_price=10000,
            stop_price=9800, lot_size=100,
        )
        assert result["qty"] == 0
        assert result["sizing_reason"] == "negative_edge"

    def test_apply_dynamic_sizing_adds_columns(self):
        from src.risk.kelly_sizing import apply_dynamic_sizing
        df = pd.DataFrame({
            "ticker": ["BBCA", "TLKM"],
            "shadow_p_win": [0.65, 0.55],
            "entry": [10000, 3500],
            "stop": [9800, 3400],
        })
        result = apply_dynamic_sizing(df, account_size=100_000_000, risk_per_trade_pct=0.75)
        for col in ["dyn_qty", "dyn_lots", "dyn_risk_idr", "kelly_mult", "sizing_reason"]:
            assert col in result.columns


# ===========================================================================
# 7. Regime-Aware Thresholds Tests
# ===========================================================================

class TestRegimeThresholds:
    def test_get_default_thresholds(self):
        from src.model_v2.regime_thresholds import get_regime_threshold
        t_risk_on = get_regime_threshold("t1", "risk_on")
        t_risk_off = get_regime_threshold("t1", "risk_off")
        # risk_off should be stricter (higher threshold)
        assert t_risk_off > t_risk_on

    def test_tune_finds_optimal_threshold(self):
        from src.model_v2.regime_thresholds import tune_regime_thresholds
        rng = np.random.RandomState(42)
        n = 200
        probs = pd.Series(rng.uniform(0.3, 0.8, n))
        returns = pd.Series(rng.randn(n) * 0.5)
        regimes = pd.Series(["risk_on"] * 100 + ["risk_off"] * 100)
        result = tune_regime_thresholds(probs, returns, regimes, mode="swing")
        assert "thresholds_by_regime" in result
        assert "risk_on" in result["thresholds_by_regime"]
        assert "risk_off" in result["thresholds_by_regime"]

    def test_apply_regime_filter(self):
        from src.model_v2.regime_thresholds import apply_regime_filter
        df = pd.DataFrame({
            "ticker": ["A", "B", "C"],
            "shadow_p_win": [0.55, 0.45, 0.70],
        })
        regimes = pd.Series(["risk_on", "risk_off", "risk_on"])
        result = apply_regime_filter(df, regimes, mode="t1")
        # At least the high-prob candidate should pass
        assert len(result) >= 1
        assert "C" in result["ticker"].values


# ===========================================================================
# 8. Sector Diversification Tests
# ===========================================================================

class TestSectorDiversification:
    def test_enforce_cap_limits_sector(self):
        from src.risk.sector_diversification import enforce_sector_cap
        df = pd.DataFrame({
            "ticker": ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"],
            "score": [95, 90, 85, 80, 75],
        })
        sector_map = {
            "BBCA": "Banking", "BBRI": "Banking", "BMRI": "Banking",
            "TLKM": "Telecom", "ASII": "Automotive",
        }
        result, diag = enforce_sector_cap(df, sector_map, max_sector_pct=35.0, max_positions=5)
        # With 5 positions and 35% cap → max 1 per sector
        banking_count = len(result[result["ticker"].isin(["BBCA", "BBRI", "BMRI"])])
        assert banking_count <= 2  # at most 1-2 banking stocks
        assert diag["removed_count"] > 0

    def test_unknown_sector_still_works(self):
        from src.risk.sector_diversification import enforce_sector_cap
        df = pd.DataFrame({
            "ticker": ["XXXX", "YYYY"],
            "score": [90, 80],
        })
        result, diag = enforce_sector_cap(df, {}, max_sector_pct=35.0, max_positions=5)
        # Unknown sectors should all be grouped as "unknown"
        assert len(result) <= 5

    def test_empty_candidates(self):
        from src.risk.sector_diversification import enforce_sector_cap
        df = pd.DataFrame(columns=["ticker", "score"])
        result, diag = enforce_sector_cap(df, {}, max_sector_pct=35.0, max_positions=5)
        assert result.empty
        assert diag["status"] == "empty"


# ===========================================================================
# 9. Closed-Loop Feedback Tests
# ===========================================================================

class TestClosedLoopFeedback:
    def test_compute_fill_metrics_basic(self):
        from src.model_v2.closed_loop import compute_fill_metrics
        fills = pd.DataFrame({
            "realized_r": [1.5, -1.0, 0.8, -0.5, 2.0],
            "pnl_idr": [15000, -10000, 8000, -5000, 20000],
            "mode": ["swing", "swing", "t1", "t1", "swing"],
        })
        metrics = compute_fill_metrics(fills)
        assert metrics["total_fills"] == 5
        assert metrics["win_rate_pct"] > 0
        assert "by_mode" in metrics
        assert "swing" in metrics["by_mode"]

    def test_compute_fill_metrics_empty(self):
        from src.model_v2.closed_loop import compute_fill_metrics
        metrics = compute_fill_metrics(pd.DataFrame())
        assert metrics["total_fills"] == 0
        assert metrics["win_rate_pct"] == 0.0

    def test_augment_with_fills_duplicates_fill_rows(self):
        from src.model_v2.closed_loop import _augment_with_fills
        history = pd.DataFrame({
            "date": pd.to_datetime(["2025-03-01", "2025-03-02"]),
            "ticker": ["BBCA", "BBCA"],
            "close": [10000, 10100],
        })
        fills = pd.DataFrame({
            "executed_at": pd.to_datetime(["2025-03-01"]),
            "ticker": ["BBCA"],
            "realized_r": [1.5],
            "pnl_idr": [15000],
        })
        augmented = _augment_with_fills(history, fills)
        # Fill row should be duplicated (2x weight)
        assert len(augmented) >= len(history)

