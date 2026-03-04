from __future__ import annotations

import pandas as pd

from src.config import RiskSettings


def _to_float_series(values: object, index: pd.Index) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce")
    if series is None:
        return pd.Series(index=index, dtype="float64")
    return pd.Series(series, index=index, dtype="float64")


def _bounded_multiplier(value: float, floor: float, cap: float) -> float:
    return max(floor, min(cap, value))


def _median_or_default(values: pd.Series, default: float) -> float:
    clean = values.dropna()
    if clean.empty:
        return default
    return float(clean.median())


def _market_regime_label(
    vol_index: float,
    calm_threshold: float,
    high_threshold: float,
    stress_threshold: float,
) -> str:
    if vol_index <= calm_threshold:
        return "calm"
    if vol_index <= high_threshold:
        return "normal"
    if vol_index <= stress_threshold:
        return "high"
    return "stress"


def propose_trade_plan(picks: pd.DataFrame, risk: RiskSettings) -> pd.DataFrame:
    """Create trade levels and size for conservative risk profile."""
    if picks.empty:
        return picks.copy()

    df = picks.copy()
    entry = _to_float_series(df["close"], index=df.index)
    atr = _to_float_series(df.get("atr_14"), index=df.index).fillna(entry * 0.05)
    stop = entry - (risk.stop_atr_multiple * atr)
    risk_per_share = (entry - stop).clip(lower=0.0)

    base_risk_budget = float(risk.account_size_idr) * (float(risk.risk_per_trade_pct) / 100.0)
    lot_size = max(1, int(risk.position_lot))
    floor_mult = float(risk.volatility_floor_multiplier)
    cap_mult = float(risk.volatility_cap_multiplier)
    cap_mult = max(floor_mult, cap_mult)
    ref_atr_pct = max(1e-9, float(risk.volatility_reference_atr_pct))
    use_realized_vol = bool(getattr(risk, "volatility_use_realized_vol", True))
    ref_realized_pct = max(1e-9, float(getattr(risk, "volatility_reference_realized_pct", 2.0)))
    realized_weight = float(getattr(risk, "volatility_realized_weight", 0.35))
    realized_weight = max(0.0, min(1.0, realized_weight)) if use_realized_vol else 0.0
    realized_weight_effective = realized_weight

    vol_multiplier_market = 1.0
    vol_multiplier_asset = pd.Series([1.0] * len(df), index=df.index, dtype="float64")
    vol_multiplier_asset_atr = pd.Series([1.0] * len(df), index=df.index, dtype="float64")
    vol_multiplier_asset_realized = pd.Series([1.0] * len(df), index=df.index, dtype="float64")
    vol_multiplier = pd.Series([1.0] * len(df), index=df.index, dtype="float64")
    market_vol_index = 1.0
    market_regime_cap_enabled = bool(getattr(risk, "volatility_market_regime_cap_enabled", True))
    market_regime_label = "normal"
    market_regime_cap_raw = cap_mult
    market_regime_cap_applied = cap_mult
    if risk.volatility_targeting_enabled:
        fallback_atr_pct = ((atr / (entry + 1e-9)) * 100.0).astype(float)
        atr_pct = _to_float_series(df.get("atr_pct"), index=df.index).replace([float("inf"), float("-inf")], float("nan"))
        atr_pct = atr_pct.fillna(fallback_atr_pct).abs()

        realized_pct = _to_float_series(df.get("realized_vol_pct"), index=df.index)
        fallback_realized_pct = _to_float_series(df.get("vol_20d"), index=df.index).abs() * 100.0
        realized_pct = realized_pct.fillna(fallback_realized_pct).replace([float("inf"), float("-inf")], float("nan")).abs()
        realized_pct_median = _median_or_default(realized_pct, default=0.0)
        # Some feeds store realized vol as decimal (0.02), normalize to percent.
        if 0.0 < realized_pct_median <= 1.0:
            realized_pct = realized_pct * 100.0
            realized_pct_median = _median_or_default(realized_pct, default=0.0)
        if realized_pct_median <= 1e-9:
            realized_weight_effective = 0.0

        market_atr_pct_med = _median_or_default(atr_pct, default=0.0)
        raw_market_mult_atr = (ref_atr_pct / market_atr_pct_med) if market_atr_pct_med > 1e-9 else cap_mult
        vol_multiplier_market = _bounded_multiplier(raw_market_mult_atr, floor=floor_mult, cap=cap_mult)
        vol_multiplier_asset_atr = (ref_atr_pct / atr_pct.clip(lower=1e-9)).clip(lower=floor_mult, upper=cap_mult).fillna(cap_mult)

        raw_market_mult = raw_market_mult_atr
        raw_asset_mult = ref_atr_pct / atr_pct.clip(lower=1e-9)

        if realized_weight_effective > 0.0:
            raw_market_mult_realized = (
                (ref_realized_pct / realized_pct_median)
                if realized_pct_median > 1e-9
                else cap_mult
            )
            vol_multiplier_asset_realized = (
                ref_realized_pct / realized_pct.clip(lower=1e-9)
            ).replace([float("inf"), float("-inf")], float("nan"))
            vol_multiplier_asset_realized = vol_multiplier_asset_realized.fillna(raw_asset_mult)
            vol_multiplier_asset_realized = vol_multiplier_asset_realized.clip(lower=floor_mult, upper=cap_mult).fillna(cap_mult)

            raw_market_mult = (raw_market_mult_atr ** (1.0 - realized_weight_effective)) * (
                raw_market_mult_realized ** realized_weight_effective
            )
            raw_asset_mult_realized = (
                ref_realized_pct / realized_pct.clip(lower=1e-9)
            ).replace([float("inf"), float("-inf")], float("nan"))
            raw_asset_mult_realized = raw_asset_mult_realized.fillna(raw_asset_mult)
            raw_asset_mult = (raw_asset_mult ** (1.0 - realized_weight_effective)) * (
                raw_asset_mult_realized ** realized_weight_effective
            )

            atr_ratio = market_atr_pct_med / ref_atr_pct if ref_atr_pct > 1e-9 else 1.0
            realized_ratio = realized_pct_median / ref_realized_pct if ref_realized_pct > 1e-9 else 1.0
            market_vol_index = (max(1e-9, atr_ratio) ** (1.0 - realized_weight_effective)) * (
                max(1e-9, realized_ratio) ** realized_weight_effective
            )
        else:
            atr_ratio = market_atr_pct_med / ref_atr_pct if ref_atr_pct > 1e-9 else 1.0
            market_vol_index = max(1e-9, atr_ratio)
            vol_multiplier_asset_realized = vol_multiplier_asset_atr.copy()

        vol_multiplier_market = _bounded_multiplier(raw_market_mult, floor=floor_mult, cap=cap_mult)
        vol_multiplier_asset = raw_asset_mult.clip(lower=floor_mult, upper=cap_mult).fillna(cap_mult)

        mode = str(getattr(risk, "volatility_targeting_mode", "hybrid")).strip().lower()
        market_weight = float(getattr(risk, "volatility_market_weight", 0.5))
        market_weight = max(0.0, min(1.0, market_weight))

        if mode == "market":
            vol_multiplier = pd.Series([vol_multiplier_market] * len(df), index=df.index, dtype="float64")
        elif mode in {"asset", "per_asset", "per-asset"}:
            vol_multiplier = vol_multiplier_asset.copy()
        else:
            # Hybrid mode blends market-wide volatility and ticker-level volatility.
            vol_multiplier = (vol_multiplier_market ** market_weight) * (vol_multiplier_asset ** (1.0 - market_weight))

        calm_threshold = max(1e-9, float(getattr(risk, "volatility_market_regime_calm_threshold", 0.85)))
        high_threshold = max(calm_threshold, float(getattr(risk, "volatility_market_regime_high_threshold", 1.15)))
        stress_threshold = max(high_threshold, float(getattr(risk, "volatility_market_regime_stress_threshold", 1.5)))
        market_regime_label = _market_regime_label(
            vol_index=market_vol_index,
            calm_threshold=calm_threshold,
            high_threshold=high_threshold,
            stress_threshold=stress_threshold,
        )

        market_regime_cap_raw = {
            "calm": float(getattr(risk, "volatility_market_regime_calm_max_mult", cap_mult)),
            "normal": float(getattr(risk, "volatility_market_regime_normal_max_mult", cap_mult)),
            "high": float(getattr(risk, "volatility_market_regime_high_max_mult", cap_mult)),
            "stress": float(getattr(risk, "volatility_market_regime_stress_max_mult", cap_mult)),
        }.get(market_regime_label, cap_mult)

        market_regime_cap_applied = cap_mult
        if market_regime_cap_enabled:
            market_regime_cap_applied = max(floor_mult, min(cap_mult, market_regime_cap_raw))

        vol_multiplier = vol_multiplier.clip(lower=floor_mult, upper=market_regime_cap_applied).fillna(floor_mult)

    risk_budget = base_risk_budget * vol_multiplier
    raw_shares = (risk_budget / (risk_per_share + 1e-9)).fillna(0.0)
    shares = ((raw_shares // lot_size) * lot_size).astype(int).clip(lower=0)

    max_position_pct = float(getattr(risk, "max_position_exposure_pct", 0.0))
    if max_position_pct > 0:
        max_position_value = float(risk.account_size_idr) * (max_position_pct / 100.0)
        safe_entry = entry.where(entry > 0, 1.0)
        max_shares = ((max_position_value / safe_entry) // lot_size) * lot_size
        max_shares = max_shares.fillna(0.0).clip(lower=0.0).astype(int)
        shares = pd.concat([shares, max_shares], axis=1).min(axis=1).astype(int)

    tp1 = entry + (risk.tp1_r_multiple * risk_per_share)
    tp2 = entry + (risk.tp2_r_multiple * risk_per_share)

    df["entry"] = entry.round(2)
    df["stop"] = stop.round(2)
    df["tp1"] = tp1.round(2)
    df["tp2"] = tp2.round(2)
    df["risk_per_share"] = risk_per_share.round(2)
    df["size"] = shares
    df["position_value"] = (shares * entry).round(0)
    df["risk_budget_base"] = round(float(base_risk_budget), 2)
    df["risk_budget_effective"] = risk_budget.round(2)
    df["vol_target_multiplier"] = vol_multiplier.round(4)
    df["vol_target_multiplier_market"] = round(float(vol_multiplier_market), 4)
    df["vol_target_multiplier_asset"] = vol_multiplier_asset.round(4)
    df["vol_target_multiplier_asset_atr"] = vol_multiplier_asset_atr.round(4)
    df["vol_target_multiplier_asset_realized"] = vol_multiplier_asset_realized.round(4)
    df["vol_target_market_vol_index"] = round(float(market_vol_index), 4)
    df["vol_target_market_regime"] = market_regime_label
    df["vol_target_regime_cap_enabled"] = bool(market_regime_cap_enabled)
    df["vol_target_regime_cap"] = round(float(market_regime_cap_applied), 4)
    df["vol_target_regime_cap_raw"] = round(float(market_regime_cap_raw), 4)
    df["vol_target_realized_weight"] = round(float(realized_weight_effective), 4)
    df["vol_target_ref_realized_pct"] = round(float(ref_realized_pct), 4)

    # Per-mode cap; final execution still capped globally by max_positions.
    if {"mode", "score"} <= set(df.columns):
        df = df.sort_values(["mode", "score"], ascending=[True, False]).reset_index(drop=True)
    return df


def apply_global_position_limit(
    plan: pd.DataFrame,
    max_positions: int,
    max_positions_by_mode: dict[str, int] | None = None,
    mode_priority: list[str] | None = None,
) -> pd.DataFrame:
    if plan.empty:
        return plan.copy()

    limit_total = max(0, int(max_positions))
    if limit_total == 0:
        return plan.iloc[0:0].copy()

    df = plan.copy()
    if "score" in df.columns:
        df = df.sort_values("score", ascending=False).copy()

    mode_priority = [str(m).strip().lower() for m in (mode_priority or []) if str(m).strip()]
    if mode_priority and "mode" in df.columns:
        fallback_rank = len(mode_priority)
        priority_rank = {mode: i for i, mode in enumerate(mode_priority)}
        df["__mode_priority"] = df["mode"].astype(str).str.lower().map(priority_rank).fillna(fallback_rank).astype(int)
        if "score" in df.columns:
            df = df.sort_values(["__mode_priority", "score"], ascending=[True, False]).copy()
        else:
            df = df.sort_values(["__mode_priority"]).copy()

    limits: dict[str, int] = {}
    for mode, raw_limit in (max_positions_by_mode or {}).items():
        try:
            parsed = int(raw_limit)
        except Exception:
            continue
        if parsed >= 0:
            limits[str(mode).strip().lower()] = parsed

    if "mode" not in df.columns or not limits:
        out = df.head(limit_total).copy()
        return out.drop(columns=["__mode_priority"], errors="ignore")

    selected_idx: list[int] = []
    mode_counts: dict[str, int] = {}
    for idx, row in df.iterrows():
        if len(selected_idx) >= limit_total:
            break
        mode = str(row.get("mode", "")).strip().lower()
        mode_cap = limits.get(mode, limit_total)
        if mode_counts.get(mode, 0) >= mode_cap:
            continue
        selected_idx.append(idx)
        mode_counts[mode] = mode_counts.get(mode, 0) + 1

    out = df.loc[selected_idx].copy()
    return out.drop(columns=["__mode_priority"], errors="ignore")
