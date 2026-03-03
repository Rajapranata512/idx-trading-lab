from __future__ import annotations

import json
import os
import time
from urllib import parse, request

import pandas as pd

from src.config import RestProviderSettings
from src.ingest.providers.base import PriceProvider


def _extract_by_path(payload: object, path: str) -> object:
    if not path:
        return payload
    cur = payload
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return []
    return cur


def _resolve_env_value(value: str) -> str:
    """Resolve ${ENV_NAME} placeholders, leave raw value when not matched."""
    txt = str(value)
    if txt.startswith("${") and txt.endswith("}") and len(txt) > 3:
        env_name = txt[2:-1].strip()
        return os.getenv(env_name, "")
    return txt


def _resolved_dict(values: dict[str, str]) -> dict[str, str]:
    return {k: _resolve_env_value(v) for k, v in values.items()}


class RestEodProvider(PriceProvider):
    """Generic REST provider with configurable query params and column mapping.

    Supports:
    - single request mode via `base_url`
    - per-ticker mode via `base_url_template` containing `{ticker}`
    """

    def __init__(self, settings: RestProviderSettings) -> None:
        self.settings = settings

    def _request_json(self, url: str) -> object:
        headers = _resolved_dict(self.settings.headers or {})
        req = request.Request(url=url, headers=headers)
        with request.urlopen(req, timeout=self.settings.timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw)

    def _map_rows(self, rows: object, ticker: str | None = None) -> pd.DataFrame:
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise ValueError("REST response data is not list-like")

        df = pd.DataFrame(rows)
        mapped: dict[str, pd.Series] = {}
        for canonical_col, source_col in self.settings.column_mapping.items():
            if canonical_col == "ticker" and source_col not in df.columns:
                if ticker is None:
                    raise ValueError("Ticker mapping missing and ticker context unavailable")
                mapped[canonical_col] = pd.Series([ticker] * len(df))
                continue
            if source_col not in df.columns:
                raise ValueError(f"Missing mapped source column: {source_col}")
            mapped[canonical_col] = df[source_col]
        return pd.DataFrame(mapped)

    def _build_url(
        self,
        base_url: str,
        params: dict[str, str],
        ticker: str | None = None,
    ) -> str:
        target = base_url
        if "{ticker}" in target:
            if not ticker:
                raise ValueError("Ticker required for base_url_template mode")
            symbol = f"{ticker}{self.settings.ticker_suffix}".upper()
            target = target.replace("{ticker}", parse.quote(symbol, safe=""))
        if params:
            return f"{target}?{parse.urlencode(params)}"
        return target

    def fetch_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        tickers: list[str] | None = None,
    ) -> pd.DataFrame:
        base_params: dict[str, str] = _resolved_dict(dict(self.settings.query_params))
        if start_date:
            base_params[self.settings.date_from_param_name] = start_date
        if end_date:
            base_params[self.settings.date_to_param_name] = end_date

        template = (self.settings.base_url_template or "").strip()
        if template:
            if not tickers:
                raise ValueError("Ticker list required in per-ticker REST mode")
            frames: list[pd.DataFrame] = []
            for ticker in sorted({t.upper().strip() for t in tickers}):
                url = self._build_url(base_url=template, params=base_params, ticker=ticker)
                payload = self._request_json(url=url)
                rows = _extract_by_path(payload, self.settings.response_data_path)
                frame = self._map_rows(rows, ticker=ticker)
                frames.append(frame)
                if self.settings.sleep_seconds_between_requests > 0:
                    time.sleep(self.settings.sleep_seconds_between_requests)
            if not frames:
                return pd.DataFrame(columns=list(self.settings.column_mapping.keys()))
            return pd.concat(frames, ignore_index=True, sort=False)

        # Single request mode.
        params = dict(base_params)
        if tickers:
            params[self.settings.ticker_param_name] = ",".join(sorted(set(tickers)))
        url = self._build_url(base_url=self.settings.base_url, params=params)
        payload = self._request_json(url=url)
        rows = _extract_by_path(payload, self.settings.response_data_path)
        return self._map_rows(rows, ticker=None)
