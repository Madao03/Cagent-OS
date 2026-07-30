"""Binance derivatives adapter — funding rate, OI, long/short ratio (free, no key).

All endpoints are public (no API key required).

Caliber rules (CRITICAL):
  - Funding rate is native 8h value. Stored as-is + `interval=8h`.
    Annualized = rate × 3 × 365 — but we store NATIVE, never annualized.
  - OI has three units (contracts / coin-margined / USDT-margined).
    Must store `unit` alongside the value.
  - Single venue (Binance). Must label `venue=binance`, never "全市场".

Endpoints:
  /fapi/v1/fundingRate        — funding rate history
  /fapi/v1/premiumIndex       — current funding rate + mark price
  /fapi/v1/openInterest       — current OI
  /futures/data/openInterestHist — OI history
  /futures/data/globalLongShortAccountRatio — long/short account ratio
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData

logger = logging.getLogger(__name__)

_BASE_FUTURES = "https://fapi.binance.com"
_BASE_DATA = "https://fapi.binance.com"

_THROTTLE_MIN_INTERVAL = 0.15  # Binance allows 1200 req/min, be conservative
_last_request_time = 0.0


def _throttle() -> None:
    global _last_request_time
    elapsed = time.perf_counter() - _last_request_time
    if elapsed < _THROTTLE_MIN_INTERVAL:
        time.sleep(_THROTTLE_MIN_INTERVAL - elapsed)
    _last_request_time = time.perf_counter()


class BinanceDerivativesAdapter(DataSourceAdapter):
    """Binance Futures — funding rate, OI, long/short ratio.

    All public endpoints, no API key. Single-venue data — must label venue.
    """

    tier = 1
    name = "binance_derivatives"

    async def get_funding_rate(self, symbol: str = "BTCUSDT") -> dict[str, Any] | None:
        """Current funding rate + mark price.

        Returns native 8h rate (NOT annualized). Caller must not annualize
        without explicit labeling.
        """
        symbol = symbol.upper()
        data = await self._fetch_json(
            f"{_BASE_FUTURES}/fapi/v1/premiumIndex",
            params={"symbol": symbol},
        )
        if not data:
            return None

        rate = self._safe_float(data.get("lastFundingRate"))
        return {
            "symbol": symbol,
            "funding_rate_8h": rate,
            "funding_rate_annualized": rate * 3 * 365 if rate is not None else None,
            "interval": "8h",
            "mark_price": self._safe_float(data.get("markPrice")),
            "index_price": self._safe_float(data.get("indexPrice")),
            "next_funding_time": data.get("nextFundingTime"),
            "venue": "binance",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "binance_futures",
            "definition": "native 8h funding rate (not annualized by default)",
        }

    async def get_funding_rate_history(
        self, symbol: str = "BTCUSDT", limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Historical funding rates (last N entries)."""
        symbol = symbol.upper()
        data = await self._fetch_json(
            f"{_BASE_FUTURES}/fapi/v1/fundingRate",
            params={"symbol": symbol, "limit": limit},
        )
        if not data:
            return []
        return [
            {
                "symbol": symbol,
                "funding_rate_8h": self._safe_float(e.get("fundingRate")),
                "interval": "8h",
                "time": e.get("fundingTime"),
                "venue": "binance",
            }
            for e in data
        ]

    async def get_open_interest(self, symbol: str = "BTCUSDT") -> dict[str, Any] | None:
        """Current open interest.

        ⚠️ Unit: Binance U本位永续返回的是基础资产数量（如 BTC 数量），
        不是"张"（coin-margined 才是张），也不是 USD。
        Multiply by mark_price for USD-denominated OI.
        """
        symbol = symbol.upper()
        data = await self._fetch_json(
            f"{_BASE_FUTURES}/fapi/v1/openInterest",
            params={"symbol": symbol},
        )
        if not data:
            return None

        oi_contracts = self._safe_float(data.get("openInterest"))
        return {
            "symbol": symbol,
            "open_interest": oi_contracts,
            "unit": "base_asset",  # U本位永续返回基础资产数量（如 BTC），不是张也不是 USD
            "venue": "binance",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "binance_futures",
        }

    async def get_open_interest_history(
        self, symbol: str = "BTCUSDT", period: str = "1d", limit: int = 30,
    ) -> list[dict[str, Any]]:
        """OI history. period: 5m/15m/30m/1h/2h/4h/6h/12h/1d."""
        symbol = symbol.upper()
        data = await self._fetch_json(
            f"{_BASE_DATA}/futures/data/openInterestHist",
            params={"symbol": symbol, "period": period, "limit": limit},
        )
        if not data:
            return []
        return [
            {
                "symbol": symbol,
                "oi_value": self._safe_float(e.get("sumOpenInterest")),
                "oi_value_usd": self._safe_float(e.get("sumOpenInterestValue")),
                "timestamp": e.get("timestamp"),
                "venue": "binance",
            }
            for e in data
        ]

    async def get_long_short_ratio(
        self, symbol: str = "BTCUSDT", period: str = "1d", limit: int = 7,
    ) -> list[dict[str, Any]]:
        """Long/short account ratio history."""
        symbol = symbol.upper()
        data = await self._fetch_json(
            f"{_BASE_DATA}/futures/data/globalLongShortAccountRatio",
            params={"symbol": symbol, "period": period, "limit": limit},
        )
        if not data:
            return []
        return [
            {
                "symbol": symbol,
                "long_short_ratio": self._safe_float(e.get("longShortRatio")),
                "long_account": self._safe_float(e.get("longAccount")),
                "short_account": self._safe_float(e.get("shortAccount")),
                "timestamp": e.get("timestamp"),
                "venue": "binance",
            }
            for e in data
        ]

    async def get_derivatives_snapshot(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        """One-call derivatives snapshot: funding + OI + long/short."""
        funding, oi = await asyncio.gather(
            self.get_funding_rate(symbol),
            self.get_open_interest(symbol),
            return_exceptions=True,
        )

        return {
            "symbol": symbol.upper(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "binance_futures",
            "venue": "binance",
            "funding_rate": funding if isinstance(funding, dict) else None,
            "open_interest": oi if isinstance(oi, dict) else None,
        }

    async def fetch(self, metric: str, **params: Any) -> RawData:
        symbol = str(params.get("symbol", "BTCUSDT"))
        if metric == "funding_rate":
            value = await self.get_funding_rate(symbol)
        elif metric == "funding_rate_history":
            limit = int(params.get("limit", 30))
            value = await self.get_funding_rate_history(symbol, limit)
        elif metric == "open_interest":
            value = await self.get_open_interest(symbol)
        elif metric == "oi_history":
            period = str(params.get("period", "1d"))
            limit = int(params.get("limit", 30))
            value = await self.get_open_interest_history(symbol, period, limit)
        elif metric == "long_short_ratio":
            period = str(params.get("period", "1d"))
            limit = int(params.get("limit", 7))
            value = await self.get_long_short_ratio(symbol, period, limit)
        elif metric == "derivatives_snapshot":
            value = await self.get_derivatives_snapshot(symbol)
        else:
            value = await self.get_derivatives_snapshot(symbol)

        return RawData(source="binance_derivatives", metric=metric, value=value,
                       fetched_at=datetime.now(timezone.utc).isoformat())

    async def health_check(self) -> DataSourceHealth:
        try:
            _throttle()
            resp = await asyncio.to_thread(
                requests.get, f"{_BASE_FUTURES}/fapi/v1/ping", timeout=8,
            )
            if resp.status_code == 200:
                return DataSourceHealth(available=True)
            return DataSourceHealth(available=False, error_message=f"HTTP {resp.status_code}")
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))

    async def _fetch_json(self, url: str, params: dict | None = None) -> Any:
        _throttle()
        try:
            resp = await asyncio.to_thread(
                requests.get, url, params=params or {}, timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("Binance %s → HTTP %d", url, resp.status_code)
                return None
            return resp.json()
        except Exception as exc:
            logger.warning("Binance fetch failed %s: %s", url, exc)
            return None

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
