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


class IntradaySettings(BaseModel):
    enabled: bool = True
    timeframe: str = "5m"
    lookback_minutes: int = 240
    poll_seconds: int = 60
    max_rows_per_ticker: int = 600
    canonical_prices_path: str = "data/raw/prices_intraday.csv"
    fallback_csv_path: str = "data/raw/prices_intraday.sample.csv"
    allow_sample_fallback: bool = True
    websocket_enabled: bool = False
    websocket_url: str = ""
    websocket_subscribe_payload: str = ""
    websocket_timeout_seconds: int = 15
    reconnect_max_attempts: int = 8
    reconnect_backoff_seconds: int = 2
    reconnect_max_backoff_seconds: int = 60
    auto_refresh_web_seconds: int = 30
    min_avg_volume_20bars: float = 50000.0
    min_live_score: float = 70.0
    top_n: int = 15


class DataSettings(BaseModel):
    timezone: str = "Asia/Jakarta"
    canonical_prices_path: str = "data/raw/prices_daily.csv"
    fallback_csv_path: str = "data/raw/prices_daily.sample.csv"
    allow_sample_fallback: bool = False
    universe_csv_path: str = "data/reference/universe_lq45_idx30.csv"
    provider: ProviderSettings
    universe_auto_update: UniverseAutoUpdateSettings = Field(default_factory=UniverseAutoUpdateSettings)
    intraday: IntradaySettings = Field(default_factory=IntradaySettings)


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
    active_modes: list[str] = Field(default_factory=lambda: ["swing", "t1"])
    min_live_score_t1: float = 95.0
    min_live_score_swing: float = 65.0
    event_risk: EventRiskSettings = Field(default_factory=EventRiskSettings)


class RiskSettings(BaseModel):
    account_size_idr: float = 10000000
    risk_per_trade_pct: float = 0.75
    max_positions: int = 3
    max_positions_t1: int = 1
    max_positions_swing: int = 3
    execution_mode_priority: list[str] = Field(default_factory=lambda: ["swing", "t1"])
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


class ModelV2Settings(BaseModel):
    enabled: bool = True
    shadow_mode: bool = True
    auto_train_enabled: bool = True
    auto_train_interval_days: int = 7
    model_dir: str = "models/model_v2"
    state_path: str = "reports/model_v2_state.json"
    min_train_rows_per_mode: int = 180
    train_lookback_days: int = 720
    horizon_days_t1: int = 1
    horizon_days_swing: int = 10
    min_prob_threshold_t1: float = 0.52
    min_prob_threshold_swing: float = 0.55
    closed_loop_retrain_enabled: bool = True
    closed_loop_state_path: str = "reports/model_v2_closed_loop_state.json"
    closed_loop_min_live_samples: int = 20
    closed_loop_min_new_fills: int = 25
    closed_loop_min_profit_factor_r: float = 1.0
    closed_loop_min_expectancy_r: float = 0.0
    closed_loop_min_hours_between_retrain: int = 24


class CoachingSettings(BaseModel):
    enabled: bool = True
    beginner_mode: bool = False
    weekly_kpi_lookback_days: int = 7
    weekly_kpi_path: str = "reports/weekly_kpi.json"
    beginner_note_path: str = "reports/beginner_coaching.md"


class ReconciliationSettings(BaseModel):
    enabled: bool = True
    auto_reconcile_on_run_daily: bool = True
    lookback_days: int = 45
    max_signal_lag_days: int = 5
    fills_csv_path: str = "data/live/trade_fills.csv"
    signal_snapshot_dir: str = "reports/snapshots"
    output_json_path: str = "reports/live_reconciliation.json"
    output_markdown_path: str = "reports/live_reconciliation.md"
    details_csv_path: str = "reports/live_reconciliation_details.csv"
    unmatched_entries_csv_path: str = "reports/live_reconciliation_unmatched_entries.csv"
    fail_on_error: bool = False


class KPIGatesSettings(BaseModel):
    gate_a_pipeline_success_rate_pct_min: float = 98.0
    gate_a_critical_errors_max: int = 0
    gate_b_swing_profit_factor_min: float = 1.25
    gate_b_swing_expectancy_min: float = 0.0
    gate_b_swing_max_dd_pct_max: float = 12.0
    gate_c_micro_live_profit_factor_min: float = 1.10
    gate_c_micro_live_expectancy_min: float = 0.0
    gate_c_operational_error_rate_pct_max: float = 1.0
    data_quality_max_stale_days: int = 3
    data_quality_max_missing_rows: int = 0
    data_quality_max_duplicate_rows: int = 0
    data_quality_max_missing_tickers: int = 0
    data_quality_outlier_ret_1d_pct: float = 25.0
    data_quality_max_outlier_rows: int = 25


class PaperTradingSettings(BaseModel):
    enabled: bool = True
    mode: str = "paper"
    auto_fill_enabled: bool = True
    slippage_pct: float = 0.15
    buy_fee_pct: float = 0.2
    sell_fee_pct: float = 0.3
    state_path: str = "reports/paper_trading_state.json"


class RolloutSettings(BaseModel):
    phase: str = "paper"  # paper | micro_live_025 | micro_live_050 | live
    micro_live_multiplier: float = 0.25
    allow_scale_up_to_half: bool = False
    rollback_on_gate_fail: bool = True


class RiskBudgetSettings(BaseModel):
    enabled: bool = True
    base_risk_budget_pct: float = 100.0
    hard_daily_stop_r: float = 2.0
    hard_weekly_stop_r: float = 6.0
    sector_exposure_cap_pct: float = 35.0


class Settings(BaseModel):
    data: DataSettings
    pipeline: PipelineSettings
    risk: RiskSettings
    backtest: BacktestSettings
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    regime: RegimeSettings = Field(default_factory=RegimeSettings)
    guardrail: GuardrailSettings = Field(default_factory=GuardrailSettings)
    model_v2: ModelV2Settings = Field(default_factory=ModelV2Settings)
    coaching: CoachingSettings = Field(default_factory=CoachingSettings)
    reconciliation: ReconciliationSettings = Field(default_factory=ReconciliationSettings)
    kpi_gates: KPIGatesSettings = Field(default_factory=KPIGatesSettings)
    paper_trading: PaperTradingSettings = Field(default_factory=PaperTradingSettings)
    rollout: RolloutSettings = Field(default_factory=RolloutSettings)
    risk_budget: RiskBudgetSettings = Field(default_factory=RiskBudgetSettings)
    notifications: NotificationSettings

    @classmethod
    def from_path(cls, path: str | Path) -> "Settings":
        payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        settings = cls.model_validate(payload)
        _validate_settings_values(settings)
        return settings


def load_settings(path: str | Path = "config/settings.json") -> Settings:
    return Settings.from_path(path)


def _validate_settings_values(settings: Settings) -> None:
    errors: list[str] = []
    allowed_modes = {"t1", "swing"}

    if settings.pipeline.min_live_score_t1 < 0:
        errors.append("pipeline.min_live_score_t1 must be >= 0")
    if settings.pipeline.min_live_score_swing < 0:
        errors.append("pipeline.min_live_score_swing must be >= 0")
    active_modes = [str(m).strip().lower() for m in settings.pipeline.active_modes if str(m).strip()]
    if not active_modes:
        errors.append("pipeline.active_modes must contain at least one mode")
    bad_active_modes = [m for m in active_modes if m not in allowed_modes]
    if bad_active_modes:
        errors.append(
            "pipeline.active_modes contains invalid mode(s): " + ", ".join(sorted(set(map(str, bad_active_modes))))
        )
    if settings.risk.risk_per_trade_pct <= 0 or settings.risk.risk_per_trade_pct > 5:
        errors.append("risk.risk_per_trade_pct must be within (0, 5]")
    if settings.risk.daily_loss_stop_r <= 0:
        errors.append("risk.daily_loss_stop_r must be > 0")
    if settings.risk.max_positions < 1:
        errors.append("risk.max_positions must be >= 1")
    if settings.risk.max_positions_t1 < 0:
        errors.append("risk.max_positions_t1 must be >= 0")
    if settings.risk.max_positions_swing < 0:
        errors.append("risk.max_positions_swing must be >= 0")

    for key, value in {
        "regime.min_breadth_ma50_pct": settings.regime.min_breadth_ma50_pct,
        "regime.min_breadth_ma20_pct": settings.regime.min_breadth_ma20_pct,
    }.items():
        if value < 0 or value > 100:
            errors.append(f"{key} must be between 0 and 100")

    if settings.regime.max_median_atr_pct <= 0:
        errors.append("regime.max_median_atr_pct must be > 0")

    for key, value in {
        "backtest.buy_fee_pct": settings.backtest.buy_fee_pct,
        "backtest.sell_fee_pct": settings.backtest.sell_fee_pct,
        "backtest.slippage_pct": settings.backtest.slippage_pct,
    }.items():
        if value < 0 or value > 5:
            errors.append(f"{key} must be between 0 and 5")

    if settings.validation.min_folds < 1:
        errors.append("validation.min_folds must be >= 1")
    if settings.validation.train_days < 30:
        errors.append("validation.train_days must be >= 30")
    if settings.validation.test_days < 20:
        errors.append("validation.test_days must be >= 20")

    intraday = settings.data.intraday
    if intraday.lookback_minutes < 30:
        errors.append("data.intraday.lookback_minutes must be >= 30")
    if intraday.poll_seconds < 5:
        errors.append("data.intraday.poll_seconds must be >= 5")
    if intraday.max_rows_per_ticker < 100:
        errors.append("data.intraday.max_rows_per_ticker must be >= 100")
    if intraday.min_avg_volume_20bars < 0:
        errors.append("data.intraday.min_avg_volume_20bars must be >= 0")
    if intraday.min_live_score < 0:
        errors.append("data.intraday.min_live_score must be >= 0")
    if intraday.top_n < 1:
        errors.append("data.intraday.top_n must be >= 1")
    if intraday.auto_refresh_web_seconds < 5:
        errors.append("data.intraday.auto_refresh_web_seconds must be >= 5")
    if intraday.reconnect_max_attempts < 1:
        errors.append("data.intraday.reconnect_max_attempts must be >= 1")

    if settings.model_v2.min_train_rows_per_mode < 50:
        errors.append("model_v2.min_train_rows_per_mode must be >= 50")
    if settings.model_v2.min_prob_threshold_t1 < 0 or settings.model_v2.min_prob_threshold_t1 > 1:
        errors.append("model_v2.min_prob_threshold_t1 must be within [0, 1]")
    if settings.model_v2.min_prob_threshold_swing < 0 or settings.model_v2.min_prob_threshold_swing > 1:
        errors.append("model_v2.min_prob_threshold_swing must be within [0, 1]")
    if settings.model_v2.closed_loop_min_live_samples < 1:
        errors.append("model_v2.closed_loop_min_live_samples must be >= 1")
    if settings.model_v2.closed_loop_min_new_fills < 1:
        errors.append("model_v2.closed_loop_min_new_fills must be >= 1")
    if settings.model_v2.closed_loop_min_profit_factor_r < 0:
        errors.append("model_v2.closed_loop_min_profit_factor_r must be >= 0")
    if settings.model_v2.closed_loop_min_hours_between_retrain < 0:
        errors.append("model_v2.closed_loop_min_hours_between_retrain must be >= 0")
    if settings.reconciliation.lookback_days < 1:
        errors.append("reconciliation.lookback_days must be >= 1")
    if settings.reconciliation.max_signal_lag_days < 0:
        errors.append("reconciliation.max_signal_lag_days must be >= 0")
    if settings.coaching.weekly_kpi_lookback_days < 1:
        errors.append("coaching.weekly_kpi_lookback_days must be >= 1")
    if settings.kpi_gates.gate_a_pipeline_success_rate_pct_min < 0 or settings.kpi_gates.gate_a_pipeline_success_rate_pct_min > 100:
        errors.append("kpi_gates.gate_a_pipeline_success_rate_pct_min must be within [0, 100]")
    if settings.kpi_gates.gate_a_critical_errors_max < 0:
        errors.append("kpi_gates.gate_a_critical_errors_max must be >= 0")
    if settings.kpi_gates.gate_b_swing_profit_factor_min < 0:
        errors.append("kpi_gates.gate_b_swing_profit_factor_min must be >= 0")
    if settings.kpi_gates.gate_b_swing_max_dd_pct_max <= 0:
        errors.append("kpi_gates.gate_b_swing_max_dd_pct_max must be > 0")
    if settings.kpi_gates.gate_c_micro_live_profit_factor_min < 0:
        errors.append("kpi_gates.gate_c_micro_live_profit_factor_min must be >= 0")
    if settings.kpi_gates.gate_c_operational_error_rate_pct_max < 0:
        errors.append("kpi_gates.gate_c_operational_error_rate_pct_max must be >= 0")
    if settings.kpi_gates.data_quality_max_stale_days < 0:
        errors.append("kpi_gates.data_quality_max_stale_days must be >= 0")
    if settings.kpi_gates.data_quality_max_missing_rows < 0:
        errors.append("kpi_gates.data_quality_max_missing_rows must be >= 0")
    if settings.kpi_gates.data_quality_max_duplicate_rows < 0:
        errors.append("kpi_gates.data_quality_max_duplicate_rows must be >= 0")
    if settings.kpi_gates.data_quality_max_missing_tickers < 0:
        errors.append("kpi_gates.data_quality_max_missing_tickers must be >= 0")
    if settings.kpi_gates.data_quality_outlier_ret_1d_pct <= 0:
        errors.append("kpi_gates.data_quality_outlier_ret_1d_pct must be > 0")
    if settings.kpi_gates.data_quality_max_outlier_rows < 0:
        errors.append("kpi_gates.data_quality_max_outlier_rows must be >= 0")
    if settings.paper_trading.mode not in {"paper", "hybrid", "live"}:
        errors.append("paper_trading.mode must be one of: paper, hybrid, live")
    if settings.paper_trading.slippage_pct < 0:
        errors.append("paper_trading.slippage_pct must be >= 0")
    if settings.rollout.phase not in {"paper", "micro_live_025", "micro_live_050", "live"}:
        errors.append("rollout.phase must be one of: paper, micro_live_025, micro_live_050, live")
    if settings.rollout.micro_live_multiplier < 0 or settings.rollout.micro_live_multiplier > 1:
        errors.append("rollout.micro_live_multiplier must be within [0, 1]")
    if settings.risk_budget.base_risk_budget_pct < 0 or settings.risk_budget.base_risk_budget_pct > 200:
        errors.append("risk_budget.base_risk_budget_pct must be within [0, 200]")
    if settings.risk_budget.hard_daily_stop_r <= 0:
        errors.append("risk_budget.hard_daily_stop_r must be > 0")
    if settings.risk_budget.hard_weekly_stop_r <= 0:
        errors.append("risk_budget.hard_weekly_stop_r must be > 0")
    if settings.risk_budget.sector_exposure_cap_pct <= 0 or settings.risk_budget.sector_exposure_cap_pct > 100:
        errors.append("risk_budget.sector_exposure_cap_pct must be within (0, 100]")

    bad_priority = [m for m in settings.risk.execution_mode_priority if str(m).strip().lower() not in allowed_modes]
    if bad_priority:
        errors.append(
            "risk.execution_mode_priority contains invalid mode(s): " + ", ".join(sorted(set(map(str, bad_priority))))
        )

    if errors:
        raise ValueError("Invalid settings:\n- " + "\n- ".join(errors))
