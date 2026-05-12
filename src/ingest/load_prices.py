from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.config import Settings
from src.ingest.providers.csv_provider import CSVProvider
from src.ingest.providers.rest_provider import RestEodProvider
from src.ingest.providers.websocket_provider import WebSocketIntradayProvider
from src.ingest.providers.yfinance_provider import YFinanceProvider
from src.ingest.validator import validate_intraday_prices, validate_prices

REQUIRED_COLS = ["date", "ticker", "open", "high", "low", "close", "volume"]
INTRADAY_REQUIRED_COLS = ["timestamp", "ticker", "open", "high", "low", "close", "volume", "timeframe"]


def _format_provider_error(exc: Exception) -> str:
    detail = str(exc).strip()
    if not detail:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {detail}"


def _is_sample_path(path: str | Path) -> bool:
    name = Path(path).name.lower()
    stem = Path(path).stem.lower()
    return ".sample." in name or stem.endswith(".sample") or "sample" in stem


def load_prices_csv(path: str, source: str = "csv") -> pd.DataFrame:
    """Load daily OHLCV data from local CSV and validate canonical output."""
    df = pd.read_csv(path)
    canonical, _ = validate_prices(df, source=source, max_staleness_days=10000)
    return canonical


def load_prices_from_provider(
    settings: Settings,
    start_date: str | None = None,
    end_date: str | None = None,
    tickers: list[str] | None = None,
) -> tuple[pd.DataFrame, str]:
    """Load daily prices using primary provider and fallback to CSV on failure."""
    provider_kind = settings.data.provider.kind.lower()

    if provider_kind == "rest":
        failures: list[str] = []
        primary = RestEodProvider(settings.data.provider.rest)
        try:
            raw = primary.fetch_daily(start_date=start_date, end_date=end_date, tickers=tickers)
            canonical, _ = validate_prices(raw, source="rest")
            return canonical, "rest"
        except Exception as exc:
            failures.append(f"rest={_format_provider_error(exc)}")
            if settings.data.provider.yfinance_fallback_enabled:
                try:
                    yf_provider = YFinanceProvider(settings.data.provider.yfinance_ticker_suffix)
                    raw = yf_provider.fetch_daily(start_date=start_date, end_date=end_date, tickers=tickers)
                    canonical, _ = validate_prices(raw, source="yfinance_fallback")
                    return canonical, "yfinance_fallback"
                except Exception as yf_exc:
                    failures.append(f"yfinance_fallback={_format_provider_error(yf_exc)}")
            fallback_path = settings.data.fallback_csv_path
            if _is_sample_path(fallback_path) and not bool(getattr(settings.data, "allow_sample_fallback", False)):
                failures.append("csv_fallback=RuntimeError: Sample fallback disabled for daily production runs")
                raise ValueError("All daily providers failed: " + " | ".join(failures))
            fallback = CSVProvider(settings.data.fallback_csv_path)
            try:
                raw = fallback.fetch_daily(start_date=start_date, end_date=end_date, tickers=tickers)
                canonical, _ = validate_prices(raw, source="csv_fallback")
                return canonical, "csv_fallback"
            except Exception as fallback_exc:
                failures.append(f"csv_fallback={_format_provider_error(fallback_exc)}")
                raise ValueError("All daily providers failed: " + " | ".join(failures)) from fallback_exc

    if provider_kind == "csv":
        provider = CSVProvider(settings.data.canonical_prices_path)
        raw = provider.fetch_daily(start_date=start_date, end_date=end_date, tickers=tickers)
        canonical, _ = validate_prices(raw, source="csv")
        return canonical, "csv"

    raise ValueError(f"Unknown provider kind: {settings.data.provider.kind}")


def load_intraday_csv(path: str, source: str = "csv_intraday", timeframe: str = "5m") -> pd.DataFrame:
    df = pd.read_csv(path)
    canonical, _ = validate_intraday_prices(
        df=df,
        source=source,
        timeframe=timeframe,
        max_staleness_minutes=1000000,
    )
    return canonical


def load_intraday_from_provider(
    settings: Settings,
    timeframe: str | None = None,
    lookback_minutes: int | None = None,
    tickers: list[str] | None = None,
) -> tuple[pd.DataFrame, str]:
    provider_kind = settings.data.provider.kind.lower()
    intraday_cfg = settings.data.intraday
    tf = str(timeframe or intraday_cfg.timeframe).strip().lower()
    lookback = int(lookback_minutes or intraday_cfg.lookback_minutes)
    start_dt = (datetime.utcnow() - timedelta(minutes=max(30, lookback))).isoformat(timespec="seconds")
    end_dt = datetime.utcnow().isoformat(timespec="seconds")
    max_rows = max(100, int(intraday_cfg.max_rows_per_ticker))
    stale_minutes = max(30, int(intraday_cfg.poll_seconds) * 3)

    if bool(intraday_cfg.websocket_enabled) and str(intraday_cfg.websocket_url).strip():
        try:
            ws = WebSocketIntradayProvider(
                url=intraday_cfg.websocket_url,
                subscribe_payload=intraday_cfg.websocket_subscribe_payload,
                timeout_seconds=intraday_cfg.websocket_timeout_seconds,
                reconnect_max_attempts=intraday_cfg.reconnect_max_attempts,
                reconnect_backoff_seconds=intraday_cfg.reconnect_backoff_seconds,
            )
            raw = ws.fetch_intraday(
                timeframe=tf,
                start_datetime=start_dt,
                end_datetime=end_dt,
                tickers=tickers,
                max_rows_per_ticker=max_rows,
            )
            canonical, _ = validate_intraday_prices(
                df=raw,
                source="websocket",
                timeframe=tf,
                max_staleness_minutes=stale_minutes,
            )
            return canonical, "websocket"
        except Exception:
            pass

    if provider_kind == "rest":
        primary = RestEodProvider(settings.data.provider.rest)
        try:
            raw = primary.fetch_intraday(
                timeframe=tf,
                start_datetime=start_dt,
                end_datetime=end_dt,
                tickers=tickers,
                max_rows_per_ticker=max_rows,
            )
            canonical, _ = validate_intraday_prices(
                df=raw,
                source="rest_intraday",
                timeframe=tf,
                max_staleness_minutes=stale_minutes,
            )
            return canonical, "rest_intraday"
        except Exception:
            if settings.data.provider.yfinance_fallback_enabled:
                try:
                    yf_provider = YFinanceProvider(settings.data.provider.yfinance_ticker_suffix)
                    raw = yf_provider.fetch_intraday(
                        timeframe=tf,
                        start_datetime=start_dt,
                        end_datetime=end_dt,
                        tickers=tickers,
                        max_rows_per_ticker=max_rows,
                    )
                    canonical, _ = validate_intraday_prices(
                        df=raw,
                        source="yfinance_intraday_fallback",
                        timeframe=tf,
                        max_staleness_minutes=stale_minutes,
                    )
                    return canonical, "yfinance_intraday_fallback"
                except Exception:
                    pass
            fallback_path = intraday_cfg.fallback_csv_path
            if _is_sample_path(fallback_path) and not bool(getattr(intraday_cfg, "allow_sample_fallback", True)):
                raise RuntimeError("Sample fallback disabled for intraday production runs")
            fallback = CSVProvider(intraday_cfg.fallback_csv_path)
            raw = fallback.fetch_intraday(
                timeframe=tf,
                start_datetime=start_dt,
                end_datetime=end_dt,
                tickers=tickers,
                max_rows_per_ticker=max_rows,
            )
            if raw.empty:
                # Local sample files are often historical snapshots; retry without time window.
                raw = fallback.fetch_intraday(
                    timeframe=tf,
                    start_datetime=None,
                    end_datetime=None,
                    tickers=tickers,
                    max_rows_per_ticker=max_rows,
                )
            canonical, _ = validate_intraday_prices(
                df=raw,
                source="csv_intraday_fallback",
                timeframe=tf,
                max_staleness_minutes=1000000,
            )
            return canonical, "csv_intraday_fallback"

    if provider_kind == "csv":
        provider = CSVProvider(intraday_cfg.canonical_prices_path)
        raw = provider.fetch_intraday(
            timeframe=tf,
            start_datetime=start_dt,
            end_datetime=end_dt,
            tickers=tickers,
            max_rows_per_ticker=max_rows,
        )
        if raw.empty:
            raw = provider.fetch_intraday(
                timeframe=tf,
                start_datetime=None,
                end_datetime=None,
                tickers=tickers,
                max_rows_per_ticker=max_rows,
            )
        canonical, _ = validate_intraday_prices(
            df=raw,
            source="csv_intraday",
            timeframe=tf,
            max_staleness_minutes=1000000,
        )
        return canonical, "csv_intraday"

    raise ValueError(f"Unknown provider kind for intraday: {settings.data.provider.kind}")
