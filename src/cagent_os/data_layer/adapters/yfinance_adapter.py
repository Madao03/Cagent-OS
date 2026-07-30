"""Yahoo Finance adapter — tier 1 free data source.

Uses the `yfinance` library (sync, wrapped in asyncio.to_thread).
Includes a circuit breaker: after 3 consecutive failures, yfinance
is marked unhealthy for 5 minutes, during which fetch() returns
immediately with an error (no network call) to avoid burning time
on a rate-limited source.

For price metrics only, a fallback to akshare US stock daily is
provided — see _try_akshare_fallback().
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
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

# Metrics that akshare can provide as fallback (price-only)
_PRICE_METRICS = {"price", "previous_close", "open", "day_high", "day_low"}


class YFinanceAdapter(DataSourceAdapter):
    name = "yfinance"
    tier = 1

    def __init__(self) -> None:
        # Circuit breaker state
        self._consecutive_failures: int = 0
        self._breaker_open_until: float = 0.0  # monotonic timestamp
        self._CB_THRESHOLD = 3        # failures to trip
        self._CB_COOLDOWN_SEC = 300   # 5 minutes

    def _is_breaker_open(self) -> bool:
        """Check if circuit breaker is currently tripped."""
        if self._breaker_open_until == 0:
            return False
        if time.monotonic() >= self._breaker_open_until:
            # Cooldown expired — allow a probe request
            self._breaker_open_until = 0
            self._consecutive_failures = 0
            logger.info("yfinance circuit breaker: cooldown expired, probing")
            return False
        return True

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._breaker_open_until = 0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._CB_THRESHOLD:
            self._breaker_open_until = time.monotonic() + self._CB_COOLDOWN_SEC
            logger.warning(
                "yfinance circuit breaker TRIPPED: %d consecutive failures, "
                "cooling down for %ds",
                self._consecutive_failures, self._CB_COOLDOWN_SEC,
            )

    async def fetch(self, metric: str, **params: Any) -> RawData:
        ticker = params.get("ticker", "")
        if not ticker:
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": "missing ticker parameter"},
            )

        # Circuit breaker: skip yfinance entirely if tripped
        if self._is_breaker_open():
            logger.debug("yfinance circuit breaker open, skipping %s/%s", ticker, metric)
            # Try akshare fallback for price metrics
            if metric in _PRICE_METRICS:
                fb = await self._try_akshare_fallback(ticker, metric)
                if fb is not None:
                    return fb
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": "circuit_breaker_open",
                              "detail": "yfinance rate-limited, retry later"},
            )

        try:
            data = await asyncio.to_thread(self._fetch_sync, ticker, metric)
            if data.value is None:
                # yfinance returned but no data — counts as failure for CB
                self._record_failure()
                # Try akshare fallback for price metrics
                if metric in _PRICE_METRICS:
                    fb = await self._try_akshare_fallback(ticker, metric)
                    if fb is not None:
                        return fb
            else:
                self._record_success()
            return data
        except Exception as exc:
            logger.warning("yfinance fetch failed: %s/%s — %s", ticker, metric, exc)
            self._record_failure()
            # Try akshare fallback for price metrics
            if metric in _PRICE_METRICS:
                fb = await self._try_akshare_fallback(ticker, metric)
                if fb is not None:
                    return fb
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": str(exc)},
            )

    async def _try_akshare_fallback(self, ticker: str, metric: str) -> RawData | None:
        """Fallback to akshare US stock daily for price metrics.

        Returns the latest close price mapped to the requested metric.
        Returns None if akshare also fails.
        """
        try:
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_us_daily, symbol=ticker, adjust="qfq")
            if df is None or len(df) == 0:
                return None
            last = df.iloc[-1]
            close = float(last.get("close", 0))
            if close == 0:
                return None
            date_str = str(last.get("date", ""))
            logger.info("yfinance → akshare fallback OK: %s close=$%.2f (%s)",
                        ticker, close, date_str)
            return RawData(
                source="akshare-us",
                metric=metric,
                value=close,
                raw_response={
                    "original_source": "akshare_stock_us_daily",
                    "price_as_of": date_str,
                    "note": "fallback from yfinance (circuit breaker or failure)",
                },
            )
        except Exception as exc:
            logger.debug("akshare US fallback also failed: %s — %s", ticker, exc)
            return None

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
        # If circuit breaker is open, report unhealthy
        if self._is_breaker_open():
            return DataSourceHealth(
                available=False,
                error_message=f"circuit_breaker_open ({self._consecutive_failures} failures)",
            )
        try:
            await asyncio.to_thread(yf.Ticker, "AAPL")
            return DataSourceHealth(available=True)
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))
