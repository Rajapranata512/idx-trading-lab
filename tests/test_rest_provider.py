from __future__ import annotations

import os

from src.config import RestProviderSettings
from src.ingest.providers.rest_provider import RestEodProvider


def test_rest_provider_template_mode_maps_ticker(monkeypatch):
    settings = RestProviderSettings(
        base_url_template="https://example.com/eod/{ticker}",
        date_from_param_name="from",
        date_to_param_name="to",
        query_params={},
        column_mapping={
            "date": "date",
            "ticker": "ticker",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        },
    )
    provider = RestEodProvider(settings)
    monkeypatch.setattr(
        provider,
        "_request_json",
        lambda url: [{"date": "2026-01-01", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100}],
    )
    out = provider.fetch_daily(start_date="2026-01-01", end_date="2026-01-02", tickers=["BBCA"])
    assert len(out) == 1
    assert out.loc[0, "ticker"] == "BBCA"


def test_rest_provider_resolves_env_query_params(monkeypatch):
    os.environ["TEST_TOKEN"] = "abc123"
    captured = {"url": ""}

    settings = RestProviderSettings(
        base_url_template="https://example.com/eod/{ticker}",
        query_params={"api_token": "${TEST_TOKEN}"},
        date_from_param_name="from",
        date_to_param_name="to",
        column_mapping={
            "date": "date",
            "ticker": "ticker",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        },
    )
    provider = RestEodProvider(settings)

    def _fake_request(url: str):
        captured["url"] = url
        return [{"date": "2026-01-01", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100}]

    monkeypatch.setattr(provider, "_request_json", _fake_request)
    provider.fetch_daily(start_date="2026-01-01", end_date="2026-01-02", tickers=["TLKM"])
    assert "api_token=abc123" in captured["url"]
