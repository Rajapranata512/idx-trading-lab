from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd

from src.ingest.providers.base import PriceProvider


class WebSocketIntradayProvider(PriceProvider):
    """Optional websocket provider for intraday OHLCV bars.

    This provider is intentionally generic: it expects websocket messages to be
    either a dict row, a list of dict rows, or a dict with `data` list.
    """

    def __init__(
        self,
        url: str,
        subscribe_payload: str = "",
        timeout_seconds: int = 15,
        reconnect_max_attempts: int = 8,
        reconnect_backoff_seconds: int = 2,
    ) -> None:
        self.url = str(url or "").strip()
        self.subscribe_payload = str(subscribe_payload or "").strip()
        self.timeout_seconds = max(3, int(timeout_seconds))
        self.reconnect_max_attempts = max(1, int(reconnect_max_attempts))
        self.reconnect_backoff_seconds = max(1, int(reconnect_backoff_seconds))

    def fetch_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        tickers: list[str] | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError("Websocket provider is intraday-only")

    def _normalize_rows(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                return [r for r in payload["data"] if isinstance(r, dict)]
            return [payload]
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        return []

    def _coerce_bar(self, row: dict[str, Any], timeframe: str) -> dict[str, Any] | None:
        timestamp = row.get("timestamp", row.get("time", row.get("datetime", row.get("date"))))
        ticker = row.get("ticker", row.get("symbol"))
        if timestamp in (None, "") or ticker in (None, ""):
            return None
        try:
            out = {
                "timestamp": pd.Timestamp(timestamp).isoformat(),
                "ticker": str(ticker).upper().strip(),
                "open": float(row.get("open", row.get("o", 0.0))),
                "high": float(row.get("high", row.get("h", 0.0))),
                "low": float(row.get("low", row.get("l", 0.0))),
                "close": float(row.get("close", row.get("c", 0.0))),
                "volume": float(row.get("volume", row.get("v", 0.0))),
                "timeframe": timeframe,
            }
        except Exception:
            return None
        return out

    def _build_subscribe_message(self, tickers: list[str], timeframe: str) -> str:
        if self.subscribe_payload:
            return (
                self.subscribe_payload
                .replace("{tickers}", ",".join(tickers))
                .replace("{timeframe}", timeframe)
            )
        return json.dumps({"type": "subscribe", "tickers": tickers, "timeframe": timeframe})

    def fetch_intraday(
        self,
        timeframe: str,
        start_datetime: str | None = None,
        end_datetime: str | None = None,
        tickers: list[str] | None = None,
        max_rows_per_ticker: int = 500,
    ) -> pd.DataFrame:
        try:
            import websocket  # type: ignore
        except Exception as exc:
            raise RuntimeError("websocket-client is not installed") from exc

        if not self.url:
            raise ValueError("Websocket URL is empty")
        if not tickers:
            raise ValueError("Ticker list is required for websocket provider")

        timeframe_norm = str(timeframe).strip().lower()
        ticker_set = sorted({str(t).upper().strip() for t in tickers if str(t).strip()})
        max_total_rows = max(1, int(max_rows_per_ticker)) * max(1, len(ticker_set))
        deadline = time.time() + float(self.timeout_seconds)
        rows: list[dict[str, Any]] = []
        last_error = ""

        for attempt in range(1, self.reconnect_max_attempts + 1):
            ws = None
            try:
                ws = websocket.create_connection(self.url, timeout=self.timeout_seconds)
                subscribe_message = self._build_subscribe_message(ticker_set, timeframe_norm)
                try:
                    parsed = json.loads(subscribe_message)
                except Exception:
                    ws.send(subscribe_message)
                else:
                    ws.send(json.dumps(parsed))

                while time.time() < deadline and len(rows) < max_total_rows:
                    remaining = max(0.5, deadline - time.time())
                    ws.settimeout(min(2.0, remaining))
                    raw = ws.recv()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        continue
                    for item in self._normalize_rows(payload):
                        bar = self._coerce_bar(item, timeframe=timeframe_norm)
                        if bar is not None and bar["ticker"] in ticker_set:
                            rows.append(bar)
                if rows:
                    break
            except Exception as exc:
                last_error = str(exc)
                if attempt < self.reconnect_max_attempts:
                    sleep_sec = min(30, self.reconnect_backoff_seconds * (2 ** (attempt - 1)))
                    time.sleep(sleep_sec)
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass

        if not rows:
            raise RuntimeError(f"No websocket intraday bars received. Last error: {last_error}")

        out = pd.DataFrame(rows)
        if start_datetime:
            out = out[pd.to_datetime(out["timestamp"], errors="coerce") >= pd.Timestamp(start_datetime)]
        if end_datetime:
            out = out[pd.to_datetime(out["timestamp"], errors="coerce") <= pd.Timestamp(end_datetime)]
        out = out.sort_values(["ticker", "timestamp"]).reset_index(drop=True)
        if max_rows_per_ticker > 0 and not out.empty:
            out = out.groupby("ticker", as_index=False, group_keys=False).tail(int(max_rows_per_ticker))
        return out.reset_index(drop=True)

