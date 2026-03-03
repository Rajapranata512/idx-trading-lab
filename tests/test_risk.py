from __future__ import annotations

import pandas as pd

from src.config import RiskSettings
from src.risk.manager import apply_global_position_limit, propose_trade_plan


def _picks_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": "BBCA", "mode": "t1", "score": 90, "close": 10000, "atr_14": 100, "reason": "ok"},
            {"ticker": "TLKM", "mode": "swing", "score": 80, "close": 4000, "atr_14": 80, "reason": "ok"},
            {"ticker": "BMRI", "mode": "t1", "score": 70, "close": 6000, "atr_14": 60, "reason": "ok"},
            {"ticker": "ASII", "mode": "swing", "score": 60, "close": 5000, "atr_14": 50, "reason": "ok"},
        ]
    )


def test_position_size_is_lot_based():
    settings = RiskSettings(position_lot=100, risk_per_trade_pct=0.75, account_size_idr=10000000)
    out = propose_trade_plan(_picks_df(), settings)
    assert (out["size"] % 100 == 0).all()


def test_risk_budget_not_exceeding_target():
    settings = RiskSettings(position_lot=100, risk_per_trade_pct=0.75, account_size_idr=10000000)
    out = propose_trade_plan(_picks_df(), settings)
    budget = settings.account_size_idr * (settings.risk_per_trade_pct / 100.0)
    per_trade_risk = out["size"] * out["risk_per_share"]
    assert (per_trade_risk <= (budget + 1e-6)).all()


def test_apply_global_position_limit():
    out = apply_global_position_limit(_picks_df(), max_positions=3)
    assert len(out) == 3


def test_volatility_targeting_reduces_size_on_high_atr_pct():
    picks = _picks_df().copy()
    picks["atr_pct"] = 10.0

    base = RiskSettings(
        position_lot=100,
        risk_per_trade_pct=0.75,
        account_size_idr=10000000,
        volatility_targeting_enabled=False,
    )
    high_vol = RiskSettings(
        position_lot=100,
        risk_per_trade_pct=0.75,
        account_size_idr=10000000,
        volatility_targeting_enabled=True,
        volatility_reference_atr_pct=3.5,
        volatility_floor_multiplier=0.5,
        volatility_cap_multiplier=1.0,
    )

    base_plan = propose_trade_plan(picks, base)
    high_vol_plan = propose_trade_plan(picks, high_vol)

    assert (high_vol_plan["size"] <= base_plan["size"]).all()
    assert (high_vol_plan["vol_target_multiplier"] <= 1.0).all()


def test_per_asset_volatility_targeting_scales_by_ticker_volatility():
    picks = pd.DataFrame(
        [
            {"ticker": "LOWV", "mode": "t1", "score": 90, "close": 10000, "atr_14": 100, "atr_pct": 2.0, "reason": "ok"},
            {"ticker": "HIGHV", "mode": "t1", "score": 85, "close": 10000, "atr_14": 100, "atr_pct": 8.0, "reason": "ok"},
        ]
    )
    settings = RiskSettings(
        position_lot=100,
        risk_per_trade_pct=0.75,
        account_size_idr=10000000,
        volatility_targeting_enabled=True,
        volatility_targeting_mode="per_asset",
        volatility_reference_atr_pct=4.0,
        volatility_floor_multiplier=0.4,
        volatility_cap_multiplier=1.2,
        volatility_market_regime_cap_enabled=False,
    )
    plan = propose_trade_plan(picks, settings)

    low = plan.loc[plan["ticker"] == "LOWV"].iloc[0]
    high = plan.loc[plan["ticker"] == "HIGHV"].iloc[0]
    assert float(low["vol_target_multiplier"]) > float(high["vol_target_multiplier"])
    assert int(low["size"]) > int(high["size"])


def test_max_position_exposure_cap_limits_position_value():
    picks = pd.DataFrame(
        [
            {"ticker": "BBCA", "mode": "t1", "score": 90, "close": 10000, "atr_14": 10, "atr_pct": 1.0, "reason": "ok"},
        ]
    )
    settings = RiskSettings(
        account_size_idr=10000000,
        risk_per_trade_pct=0.75,
        position_lot=100,
        max_position_exposure_pct=5.0,
        volatility_targeting_enabled=False,
    )
    plan = propose_trade_plan(picks, settings)

    max_position_value = settings.account_size_idr * (settings.max_position_exposure_pct / 100.0)
    assert float(plan.iloc[0]["position_value"]) <= (max_position_value + 1e-6)


def test_realized_vol_targeting_scales_down_high_realized_vol():
    picks = pd.DataFrame(
        [
            {"ticker": "LOWRV", "mode": "t1", "score": 90, "close": 10000, "atr_14": 120, "atr_pct": 3.5, "vol_20d": 0.01, "reason": "ok"},
            {"ticker": "HIGHRV", "mode": "t1", "score": 88, "close": 10000, "atr_14": 120, "atr_pct": 3.5, "vol_20d": 0.06, "reason": "ok"},
        ]
    )
    settings = RiskSettings(
        account_size_idr=10000000,
        risk_per_trade_pct=0.75,
        position_lot=100,
        volatility_targeting_enabled=True,
        volatility_targeting_mode="per_asset",
        volatility_reference_atr_pct=3.5,
        volatility_use_realized_vol=True,
        volatility_reference_realized_pct=2.0,
        volatility_realized_weight=0.8,
        volatility_floor_multiplier=0.3,
        volatility_cap_multiplier=1.2,
        volatility_market_regime_cap_enabled=False,
    )
    plan = propose_trade_plan(picks, settings)

    low = plan.loc[plan["ticker"] == "LOWRV"].iloc[0]
    high = plan.loc[plan["ticker"] == "HIGHRV"].iloc[0]
    assert float(low["vol_target_multiplier"]) > float(high["vol_target_multiplier"])
    assert int(low["size"]) > int(high["size"])


def test_market_regime_cap_reduces_multiplier_in_stress_regime():
    picks = pd.DataFrame(
        [
            {"ticker": "AAA", "mode": "t1", "score": 90, "close": 10000, "atr_14": 560, "atr_pct": 5.6, "vol_20d": 0.04, "reason": "ok"},
            {"ticker": "BBB", "mode": "swing", "score": 85, "close": 10000, "atr_14": 560, "atr_pct": 5.6, "vol_20d": 0.04, "reason": "ok"},
        ]
    )
    base = RiskSettings(
        account_size_idr=10000000,
        risk_per_trade_pct=0.75,
        position_lot=100,
        volatility_targeting_enabled=True,
        volatility_targeting_mode="market",
        volatility_reference_atr_pct=3.5,
        volatility_use_realized_vol=True,
        volatility_reference_realized_pct=2.0,
        volatility_realized_weight=0.5,
        volatility_floor_multiplier=0.3,
        volatility_cap_multiplier=1.3,
        volatility_market_regime_cap_enabled=False,
    )
    capped = RiskSettings(
        account_size_idr=base.account_size_idr,
        risk_per_trade_pct=base.risk_per_trade_pct,
        position_lot=base.position_lot,
        volatility_targeting_enabled=base.volatility_targeting_enabled,
        volatility_targeting_mode=base.volatility_targeting_mode,
        volatility_reference_atr_pct=base.volatility_reference_atr_pct,
        volatility_use_realized_vol=base.volatility_use_realized_vol,
        volatility_reference_realized_pct=base.volatility_reference_realized_pct,
        volatility_realized_weight=base.volatility_realized_weight,
        volatility_floor_multiplier=base.volatility_floor_multiplier,
        volatility_cap_multiplier=base.volatility_cap_multiplier,
        volatility_market_regime_cap_enabled=True,
        volatility_market_regime_calm_threshold=0.85,
        volatility_market_regime_high_threshold=1.15,
        volatility_market_regime_stress_threshold=1.4,
        volatility_market_regime_calm_max_mult=1.2,
        volatility_market_regime_normal_max_mult=1.0,
        volatility_market_regime_high_max_mult=0.75,
        volatility_market_regime_stress_max_mult=0.5,
    )

    base_plan = propose_trade_plan(picks, base)
    capped_plan = propose_trade_plan(picks, capped)

    assert set(capped_plan["vol_target_market_regime"].unique()) == {"stress"}
    assert (capped_plan["vol_target_regime_cap"] == 0.5).all()
    assert float(capped_plan["vol_target_multiplier"].max()) <= 0.5 + 1e-9
    assert float(capped_plan["vol_target_multiplier"].max()) < float(base_plan["vol_target_multiplier"].max())
