"""DataLayer — unified data entry point for all skills.

Every skill fetches data through this layer, never by calling external
APIs directly. This is the single place where cross-validation,
degradation, and caching are enforced.

Stage 0: single-source pass-through + PE forward dual-source validation.
Stage 1: multi-source collection, full variance detection, auto-degradation.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData
from cagent_os.data_layer.cross_validator import MetricCrossValidator, VerifiedMetric

import asyncio  # noqa: E402

logger = logging.getLogger(__name__)

# -- Cache TTL tiers (seconds) -------------------------------------------
CACHE_TTL: dict[str, int] = {
    "fwd_pe": 900, "ttm_pe": 900, "price": 300, "pb": 900, "ps": 900,
    "roe": 3600, "roa": 3600, "peg": 900, "market_cap": 900,
    "dividend_yield": 3600, "ev_ebitda": 3600, "eps_ttm": 3600,
    "eps_forward": 900, "beta": 86400, "volume": 300,
}


class DataLayer:
    def __init__(self) -> None:
        self._adapters: dict[str, DataSourceAdapter] = {}
        self._cache: dict[tuple[str, str, str], tuple[float, RawData]] = {}

    def register_source(self, adapter: DataSourceAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get_adapter(self, name: str) -> DataSourceAdapter:
        return self._adapters[name]

    @property
    def adapter_names(self) -> list[str]:
        return list(self._adapters.keys())

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check_all(self) -> dict[str, DataSourceHealth]:
        results: dict[str, DataSourceHealth] = {}
        for name, adapter in self._adapters.items():
            try:
                results[name] = await asyncio.wait_for(
                    adapter.health_check(), timeout=8,
                )
            except asyncio.TimeoutError:
                results[name] = DataSourceHealth(
                    available=False, error_message="health check timed out after 8s",
                )
                logger.warning("Health check timed out for %s", name)
            except Exception as exc:
                results[name] = DataSourceHealth(available=False, error_message=str(exc))
                logger.warning("Health check failed for %s: %s", name, exc)
        return results

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    async def fetch(self, source: str, metric: str, **params: Any) -> RawData:
        adapter = self._adapters[source]
        cache_key = (source, metric, str(params))
        ttl = CACHE_TTL.get(metric, 900)
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < ttl:
                return data
        raw = await adapter.fetch(metric, **params)
        self._cache[cache_key] = (time.time(), raw)
        return raw

    async def fetch_verified(self, ticker: str, metric: str) -> VerifiedMetric:
        """Cross-validate any metric across registered adapters.

        Runs a health check first, then validates across all available
        adapters that support the metric (currently yfinance + fin-skill).
        Returns a VerifiedMetric with confidence score, source status,
        and actionable warnings.
        """
        health = await self.health_check_all()
        available = {name for name, h in health.items() if h.available}
        sources = [
            a for a in self._adapters.values()
            if a.name in {"yfinance", "fin-skill"} and a.name in available
        ]
        unavailable = [
            name for name in {"yfinance", "fin-skill"}
            if name not in available and name in self._adapters
        ]
        if not sources:
            return VerifiedMetric(
                value=None, confidence=0.0, verification_level="failed",
                warnings=[f"All sources unavailable. Health: {health}"]
            )
        cache = self._cache
        ttl_map = CACHE_TTL

        class _CachedSource(DataSourceAdapter):
            """Transparent cache wrapper so the cross-validator hits our cache."""
            def __init__(self, inner: DataSourceAdapter) -> None:
                self._inner = inner
                self.name = inner.name
                self.tier = inner.tier

            async def fetch(self, metric: str, **params: Any) -> RawData:
                cache_key = (self.name, metric, str(params))
                ttl = ttl_map.get(metric, 900)
                if cache_key in cache:
                    ts, data = cache[cache_key]
                    if time.time() - ts < ttl:
                        return data
                raw = await self._inner.fetch(metric, **params)
                cache[cache_key] = (time.time(), raw)
                return raw

            async def health_check(self) -> DataSourceHealth:
                return await self._inner.health_check()

        validator = MetricCrossValidator(*(_CachedSource(s) for s in sources))
        try:
            result = await asyncio.wait_for(
                validator.verify(ticker, metric), timeout=25,
            )
        except asyncio.TimeoutError:
            result = VerifiedMetric(
                value=None, confidence=0.0, verification_level="failed",
                warnings=["Cross-validation timed out after 25s. One or more data sources may be unresponsive."],
            )
        if unavailable:
            result.warnings.append(
                f"Sources down during health check: {', '.join(unavailable)}"
            )
        return result
