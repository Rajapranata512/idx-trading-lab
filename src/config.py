from __future__ import annotations

import json
import copy
from pathlib import Path
from typing import Any, get_type_hints

try:
    from pydantic import BaseModel, Field
except Exception:
    class BaseModel:
        """Small fallback for environments without pydantic installed."""

        def __init__(self, **kwargs: Any) -> None:
            hints = get_type_hints(self.__class__)
            for key, typ in hints.items():
                if key in kwargs:
                    value = kwargs[key]
                else:
                    value = copy.deepcopy(getattr(self.__class__, key))
                if isinstance(value, dict) and isinstance(typ, type) and issubclass(typ, BaseModel):
                    value = typ.model_validate(value)
                setattr(self, key, value)

        @classmethod
        def model_validate(cls, payload: dict[str, Any]) -> "BaseModel":
            return cls(**payload)

    def Field(default: Any = None, default_factory: Any = None) -> Any:
        if default_factory is not None:
            return default_factory()
        return default


class RestProviderSettings(BaseModel):
    base_url: str = ""
    base_url_template: str = ""
    timeout_seconds: int = 20
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    ticker_param_name: str = "ticker"
    ticker_suffix: str = ""
    date_from_param_name: str = "start"
    date_to_param_name: str = "end"
    response_data_path: str = ""
    column_mapping: dict[str, str]
    sleep_seconds_between_requests: float = 0.0


class ProviderSettings(BaseModel):
    kind: str = "csv"
    rest: RestProviderSettings
    yfinance_fallback_enabled: bool = True
    yfinance_ticker_suffix: str = ".JK"


class UniverseSourceSettings(BaseModel):
    url: str = ""
    format: str = "csv"  # csv or json
    response_data_path: str = ""
    ticker_column: str = "ticker"
    query_params: dict[str, str] = Field(default_factory=dict)


class UniverseAutoUpdateSettings(BaseModel):
    enabled: bool = True
    interval_days: int = 7
    fail_on_error: bool = False
    state_path: str = "reports/universe_update_state.json"
    request_timeout_seconds: int = 20
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    lq45: UniverseSourceSettings = Field(default_factory=UniverseSourceSettings)
    idx30: UniverseSourceSettings = Field(default_factory=UniverseSourceSettings)


class DataSettings(BaseModel):
    timezone: str = "Asia/Jakarta"
    canonical_prices_path: str = "data/raw/prices_daily.csv"
    fallback_csv_path: str = "data/raw/prices_daily.sample.csv"
    universe_csv_path: str = "data/reference/universe_lq45_idx30.csv"
    provider: ProviderSettings
    universe_auto_update: UniverseAutoUpdateSettings = Field(default_factory=UniverseAutoUpdateSettings)


class EventRiskSourceSettings(BaseModel):
    url: str = ""
    format: str = "csv"  # csv, json, or html
    response_data_path: str = ""
    ticker_column: str = "ticker"
    status_column: str = "status"
    reason_column: str = "reason"
    start_date_column: str = "start_date"
    end_date_column: str = "end_date"
    status_override: str = ""
    source_name: str = ""
    html_keyword_any: list[str] = Field(default_factory=list)
    html_keyword_all: list[str] = Field(default_factory=list)
    html_keyword_none: list[str] = Field(default_factory=list)
    query_params: dict[str, str] = Field(default_factory=dict)


class EventRiskAutoUpdateSettings(BaseModel):
    enabled: bool = False
    interval_hours: int = 24
    fail_on_error: bool = False
    state_path: str = "reports/event_risk_update_state.json"
    request_timeout_seconds: int = 20
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    suspend: EventRiskSourceSettings = Field(
        default_factory=lambda: EventRiskSourceSettings(status_override="SUSPEND", source_name="suspend")
    )
    uma: EventRiskSourceSettings = Field(
        default_factory=lambda: EventRiskSourceSettings(status_override="UMA", source_name="uma")
    )
    material: EventRiskSourceSettings = Field(
        default_factory=lambda: EventRiskSourceSettings(status_override="MATERIAL", source_name="material")
    )


class EventRiskSettings(BaseModel):
    enabled: bool = True
    blacklist_csv_path: str = "data/reference/event_risk_blacklist.csv"
    active_statuses: list[str] = Field(
        default_factory=lambda: ["SUSPEND", "UMA", "MATERIAL", "SPECIAL_MONITORING"]
    )
    default_active_days: int = 14
    fail_on_error: bool = False
    auto_update: EventRiskAutoUpdateSettings = Field(default_factory=EventRiskAutoUpdateSettings)


class PipelineSettings(BaseModel):
    min_avg_volume_20d: float = 200000
    top_n_per_mode: int = 10
    top_n_combined: int = 20
    min_live_score_t1: float = 95.0
    min_live_score_swing: float = 65.0
    event_risk: EventRiskSettings = Field(default_factory=EventRiskSettings)


class RiskSettings(BaseModel):
    account_size_idr: float = 10000000
    risk_per_trade_pct: float = 0.75
    max_positions: int = 3
    daily_loss_stop_r: float = 2.0
    position_lot: int = 100
    stop_atr_multiple: float = 2.0
    tp1_r_multiple: float = 1.0
    tp2_r_multiple: float = 2.0
    volatility_targeting_enabled: bool = True
    volatility_reference_atr_pct: float = 3.5
    volatility_floor_multiplier: float = 0.5
    volatility_cap_multiplier: float = 1.0
    volatility_targeting_mode: str = "hybrid"  # market | per_asset | hybrid
    volatility_market_weight: float = 0.5
    volatility_use_realized_vol: bool = True
    volatility_reference_realized_pct: float = 2.0
    volatility_realized_weight: float = 0.35
    volatility_market_regime_cap_enabled: bool = True
    volatility_market_regime_calm_threshold: float = 0.85
    volatility_market_regime_high_threshold: float = 1.15
    volatility_market_regime_stress_threshold: float = 1.5
    volatility_market_regime_calm_max_mult: float = 1.15
    volatility_market_regime_normal_max_mult: float = 1.0
    volatility_market_regime_high_max_mult: float = 0.75
    volatility_market_regime_stress_max_mult: float = 0.5
    volatility_auto_recalibration_enabled: bool = True
    volatility_auto_recalibration_interval_days: int = 7
    volatility_auto_recalibration_state_path: str = "reports/volatility_recalibration_state.json"
    volatility_auto_recalibration_lookback_days: int = 252
    volatility_auto_recalibration_min_rows: int = 200
    volatility_auto_recalibration_quantile_atr: float = 0.5
    volatility_auto_recalibration_quantile_realized: float = 0.5
    volatility_auto_recalibration_min_atr_pct: float = 1.5
    volatility_auto_recalibration_max_atr_pct: float = 8.0
    volatility_auto_recalibration_min_realized_pct: float = 0.8
    volatility_auto_recalibration_max_realized_pct: float = 6.0
    volatility_auto_recalibration_min_delta_pct: float = 0.05
    max_position_exposure_pct: float = 20.0


class BacktestSettings(BaseModel):
    buy_fee_pct: float = 0.15
    sell_fee_pct: float = 0.25
    slippage_pct: float = 0.1
    equity_allocation_pct: float = 3.0
    min_trades_for_promotion: int = 150
    profit_factor_min: float = 1.2
    expectancy_min: float = 0.0
    max_drawdown_pct_limit: float = 15.0


class ValidationSettings(BaseModel):
    use_walk_forward_gate: bool = True
    train_days: int = 252
    test_days: int = 63
    step_days: int = 63
    min_folds: int = 3
    min_train_trades: int = 120
    min_oos_trades: int = 120
    threshold_grid_t1: list[float] = Field(default_factory=lambda: [85.0, 90.0, 95.0, 97.0, 100.0])
    threshold_grid_swing: list[float] = Field(default_factory=lambda: [55.0, 60.0, 65.0, 70.0, 75.0, 80.0])


class RegimeSettings(BaseModel):
    enabled: bool = True
    min_breadth_ma50_pct: float = 45.0
    min_breadth_ma20_pct: float = 50.0
    min_avg_ret20_pct: float = 0.0
    max_median_atr_pct: float = 8.0


class GuardrailSettings(BaseModel):
    kill_switch_enabled: bool = True
    rolling_trades: int = 80
    min_rolling_trades: int = 50
    min_rolling_pf: float = 1.05
    min_rolling_expectancy: float = 0.0
    cooldown_days: int = 3


class NotificationSettings(BaseModel):
    telegram_bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    telegram_chat_id_env: str = "TELEGRAM_CHAT_ID"


class Settings(BaseModel):
    data: DataSettings
    pipeline: PipelineSettings
    risk: RiskSettings
    backtest: BacktestSettings
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    regime: RegimeSettings = Field(default_factory=RegimeSettings)
    guardrail: GuardrailSettings = Field(default_factory=GuardrailSettings)
    notifications: NotificationSettings

    @classmethod
    def from_path(cls, path: str | Path) -> "Settings":
        payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(payload)


def load_settings(path: str | Path = "config/settings.json") -> Settings:
    return Settings.from_path(path)
