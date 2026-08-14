from __future__ import annotations

from collections.abc import Iterable


FEATURE_CONTRACT_VERSION = "eod-technical-v1"

CANONICAL_PRICE_COLUMNS = [
    "date",
    "ticker",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "ingested_at",
]

DERIVED_FEATURE_COLUMNS = [
    "ret_1d",
    "ret_5d",
    "ret_20d",
    "ma_20",
    "ma_50",
    "ma_200",
    "vol_20d",
    "avg_vol_20d",
    "turnover",
    "turnover_20d",
    "rsi_14",
    "atr_14",
    "atr_pct",
    "ma_slope_20",
    "ma_slope_50",
    "dist_ma_20",
    "dist_ma_50",
    "vol_60d",
    "vol_ratio",
    "ret_5d_20d_ratio",
    "high_low_range",
    "close_position",
    "volume_ratio_20d",
    "turnover_ratio_20d",
    "rsi_slope",
    "obv_slope",
    "mfi_14",
    "high_20",
    "low_20",
    "dist_high_20",
    "dist_low_20",
    "ma_gap_20_50",
    "ma_stack_bullish",
    "rank_ret_20d",
    "rank_vol_20d",
    "market_breadth_ma20_pct",
    "market_breadth_ma50_pct",
    "market_avg_ret20_pct",
    "market_median_atr_pct",
    "relative_ret_20d",
]

FEATURE_OUTPUT_COLUMNS = CANONICAL_PRICE_COLUMNS + DERIVED_FEATURE_COLUMNS


def validate_feature_columns(columns: Iterable[object]) -> None:
    actual = [str(column) for column in columns]
    if actual == FEATURE_OUTPUT_COLUMNS:
        return

    missing = [column for column in FEATURE_OUTPUT_COLUMNS if column not in actual]
    extra = [column for column in actual if column not in FEATURE_OUTPUT_COLUMNS]
    order_changed = not missing and not extra
    raise ValueError(
        "Feature contract mismatch for "
        f"{FEATURE_CONTRACT_VERSION}: missing={missing}, extra={extra}, "
        f"order_changed={order_changed}"
    )
