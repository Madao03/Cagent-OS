"""Yahoo Finance adapter — tier 1 free data source.

Uses the `yfinance` library (sync, wrapped in asyncio.to_thread).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import yfinance as yf

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData

logger = logging.getLogger(__name__)

# -- Metric → Ticker.info key mapping ---------------------------------

_INFO_KEY_MAP: dict[str, str] = {
    "fwd_pe": "forwardPE",
    "ttm_pe": "trailingPE",
    "price": "currentPrice",
    "previous_close": "previousClose",
    "open": "open",
    "day_high": "dayHigh",
    "day_low": "dayLow",
    "market_cap": "marketCap",
    "beta": "beta",
    "pb": "priceToBook",
    "ps": "priceToSalesTrailing12Months",
    "eps_ttm": "trailingEps",
    "eps_forward": "forwardEps",
    "dividend_yield": "dividendYield",
    "roe": "returnOnEquity",
    "roa": "returnOnAssets",
    "peg": "pegRatio",
    "short_ratio": "shortRatio",
    "52w_high": "fiftyTwoWeekHigh",
    "52w_low": "fiftyTwoWeekLow",
    "50d_avg": "fiftyDayAverage",
    "200d_avg": "twoHundredDayAverage",
    "volume": "volume",
    "avg_volume": "averageVolume",
    "sector": "sector",
    "industry": "industry",
    "description": "longBusinessSummary",
    "employees": "fullTimeEmployees",
    "country": "country",
    "website": "website",
    "currency": "currency",
}


class YFinanceAdapter(DataSourceAdapter):
    name = "yfinance"
    tier = 1

    async def fetch(self, metric: str, **params: Any) -> RawData:
        ticker = params.get("ticker", "")
        if not ticker:
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": "missing ticker parameter"},
            )

        try:
            data = await asyncio.to_thread(self._fetch_sync, ticker, metric)
            return data
        except Exception as exc:
            logger.warning("yfinance fetch failed: %s/%s — %s", ticker, metric, exc)
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": str(exc)},
            )

    def _fetch_sync(self, ticker: str, metric: str) -> RawData:
        stock = yf.Ticker(ticker)
        info = stock.info or {}

        if metric in _INFO_KEY_MAP:
            key = _INFO_KEY_MAP[metric]
            value = info.get(key)
            return RawData(
                source=self.name, metric=metric, value=value,
                raw_response={k: info.get(k) for k in [key, "symbol", "shortName", "exchange"]},
            )

        if metric == "full_quote":
            # Return everything — used for debugging / full analysis
            return RawData(
                source=self.name, metric=metric, value=info,
                raw_response=info,
            )

        # Generic: try info dict directly
        value = info.get(metric)
        return RawData(
            source=self.name, metric=metric, value=value,
            raw_response={"lookup_key": metric, "found": value is not None},
        )

    async def health_check(self) -> DataSourceHealth:
        try:
            await asyncio.to_thread(yf.Ticker, "AAPL")
            return DataSourceHealth(available=True)
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))
