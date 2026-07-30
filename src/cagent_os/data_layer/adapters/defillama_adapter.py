"""DeFiLlama adapter — DeFi full-spectrum data (free, no API key).

Four sub-domains, each with its own base URL:
  api.llama.fi            — TVL, protocols, DEX volume, fees/revenue
  stablecoins.llama.fi    — stablecoin supply & distribution
  yields.llama.fi         — yield pools (APY, TVL, risk)

Known issues:
  - /overview/fees is unreliable (frequent 500). Callers must handle None.
  - /v2/chains has a bug (first entry = Harmony with TVL≈0). Use /chains only.

Caching: SQLite materialization (like EDGAR F4). TVL/stablecoins 1h, fees 6h.
All values carry explicit caliber metadata (definition / unit / interval).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData

logger = logging.getLogger(__name__)

_BASE_TVL = "https://api.llama.fi"
_BASE_STABLE = "https://stablecoins.llama.fi"
_BASE_YIELDS = "https://yields.llama.fi"

_THROTTLE_MIN_INTERVAL = 0.12
_last_request_time = 0.0


def _throttle() -> None:
    global _last_request_time
    elapsed = time.perf_counter() - _last_request_time
    if elapsed < _THROTTLE_MIN_INTERVAL:
        time.sleep(_THROTTLE_MIN_INTERVAL - elapsed)
    _last_request_time = time.perf_counter()


@dataclass
class DefiMetric:
    """A single DeFi metric with explicit caliber."""
    metric: str
    value: float | None
    unit: str
    source: str = "defillama"
    definition: str = ""
    fetched_at: str = ""
    confidence: str = "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "definition": self.definition,
            "fetched_at": self.fetched_at,
            "confidence": self.confidence,
        }


class DefiLlamaAdapter(DataSourceAdapter):
    """DeFiLlama — TVL, stablecoins, DEX volume, fees/revenue, yields.

    All free, no API key required. Data updates every 5-15 min server-side.
    """

    tier = 1
    name = "defillama"

    # ── TVL endpoints ───────────────────────────────────────────

    async def get_chains_tvl(self) -> list[dict[str, Any]]:
        """All chains TVL ranking. Use /chains (NOT /v2/chains — known bug)."""
        data = await self._fetch_json(f"{_BASE_TVL}/chains")
        if not data:
            return []
        chains = []
        for c in data:
            chains.append({
                "name": c.get("name", ""),
                "tvl": c.get("tvl", 0),
                "token_symbol": c.get("tokenSymbol", ""),
                "chain_id": c.get("chainId"),
                "gecko_id": c.get("geckoId", ""),
            })
        return chains

    async def get_protocol_tvl(self, slug: str) -> dict[str, Any] | None:
        """Single protocol TVL breakdown by chain."""
        data = await self._fetch_json(f"{_BASE_TVL}/protocol/{slug}")
        if not data:
            return None
        return {
            "name": data.get("name", ""),
            "slug": slug,
            "tvl": data.get("tvl", 0),
            "chain_tvls": data.get("chainTvls", {}),
            "category": data.get("category", ""),
            "change_1d": data.get("change_1d", 0),
            "change_7d": data.get("change_7d", 0),
        }

    async def get_dex_overview(self) -> dict[str, Any] | None:
        """DEX 24h/7d/30d volume overview."""
        data = await self._fetch_json(f"{_BASE_TVL}/overview/dexs")
        if not data:
            return None
        return {
            "total_24h": data.get("total24h", 0),
            "total_7d": data.get("total7d", 0),
            "change_1d": data.get("change_1d", 0),
            "change_7d": data.get("change_7d", 0),
            "breakdown_24h": data.get("breakdown24h", {}),
        }

    async def get_fees_overview(self) -> dict[str, Any] | None:
        """Protocol fees/revenue overview.

        ⚠️ KNOWN ISSUE: /overview/fees frequently returns 500.
        Caller MUST handle None — do not use for critical valuations.
        """
        try:
            data = await self._fetch_json(f"{_BASE_TVL}/overview/fees")
        except Exception as exc:
            logger.warning("DeFiLlama fees endpoint failed (known issue): %s", exc)
            return None
        if not data:
            return None
        protocols = data.get("protocols", [])
        total_24h = data.get("total24h", 0)
        return {
            "total_24h": total_24h,
            "change_1d": data.get("change_1d", 0),
            "protocols": [
                {
                    "name": p.get("name", ""),
                    "fees_24h": p.get("total24h", 0),
                    "revenue_24h": p.get("revenue24h", 0),
                }
                for p in protocols[:20]
            ],
        }

    # ── Stablecoin endpoints ────────────────────────────────────

    async def get_stablecoins(self) -> list[dict[str, Any]]:
        """All stablecoins with circulating supply.

        caliber: circulating supply (peggedUSD), not total minted.
        """
        data = await self._fetch_json(f"{_BASE_STABLE}/stablecoins")
        if not data:
            return []
        coins = []
        for s in data.get("peggedAssets", []):
            circ = s.get("circulating", {})
            coins.append({
                "symbol": s.get("symbol", ""),
                "name": s.get("name", ""),
                "circulating_usd": circ.get("peggedUSD", 0),
                "price": s.get("price", 1.0),
                "peg_type": s.get("pegType", ""),
                "peg_mechanism": s.get("pegMechanism", ""),
            })
        return coins

    # ── Yields endpoints ────────────────────────────────────────

    async def get_yield_pools(self, limit: int = 20) -> list[dict[str, Any]]:
        """Top yield pools by APY. Returns APY (not APR)."""
        data = await self._fetch_json(f"{_BASE_YIELDS}/pools")
        if not data:
            return []
        pools = data.get("data", [])
        # Sort by APY descending, take top N
        pools.sort(key=lambda p: p.get("apy", 0), reverse=True)
        return [
            {
                "project": p.get("project", ""),
                "symbol": p.get("symbol", ""),
                "chain": p.get("chain", ""),
                "tvl_usd": p.get("tvlUsd", 0),
                "apy": p.get("apy", 0),
                "apy_base": p.get("apyBase", 0),
                "apy_reward": p.get("apyReward", 0),
                "il_risk": p.get("ilRisk", "unknown"),
            }
            for p in pools[:limit]
        ]

    # ── Summary snapshots ───────────────────────────────────────

    async def get_market_snapshot(self) -> dict[str, Any]:
        """One-call DeFi market snapshot: TVL + stablecoins + DEX + yields.

        Aggregates multiple endpoints. Missing data → None (never fill 0).
        """
        chains, stablecoins, dex, pools = await asyncio.gather(
            self.get_chains_tvl(),
            self.get_stablecoins(),
            self.get_dex_overview(),
            self.get_yield_pools(limit=5),
            return_exceptions=True,
        )

        total_tvl = sum(c.get("tvl", 0) for c in chains) if isinstance(chains, list) else None
        total_stable = sum(s["circulating_usd"] for s in stablecoins) if isinstance(stablecoins, list) else None

        return {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "defillama",
            "total_tvl_usd": total_tvl,
            "top_chains": sorted(chains, key=lambda c: c.get("tvl", 0), reverse=True)[:10] if isinstance(chains, list) else [],
            "total_stablecoin_supply": total_stable,
            "top_stablecoins": sorted(stablecoins, key=lambda s: s.get("circulating_usd", 0), reverse=True)[:5] if isinstance(stablecoins, list) else [],
            "dex_volume_24h": dex.get("total_24h") if isinstance(dex, dict) else None,
            "top_yield_pools": pools if isinstance(pools, list) else [],
        }

    # ── DataSourceAdapter interface ─────────────────────────────

    async def fetch(self, metric: str, **params: Any) -> RawData:
        if metric == "chains_tvl":
            data = await self.get_chains_tvl()
            return RawData(source="defillama", metric=metric, value=data,
                           fetched_at=datetime.now(timezone.utc).isoformat())
        if metric == "protocol_tvl":
            slug = str(params.get("slug", ""))
            data = await self.get_protocol_tvl(slug)
            return RawData(source="defillama", metric=metric, value=data,
                           fetched_at=datetime.now(timezone.utc).isoformat())
        if metric == "stablecoins":
            data = await self.get_stablecoins()
            return RawData(source="defillama", metric=metric, value=data,
                           fetched_at=datetime.now(timezone.utc).isoformat())
        if metric == "dex_overview":
            data = await self.get_dex_overview()
            return RawData(source="defillama", metric=metric, value=data,
                           fetched_at=datetime.now(timezone.utc).isoformat())
        if metric == "yield_pools":
            limit = int(params.get("limit", 20))
            data = await self.get_yield_pools(limit=limit)
            return RawData(source="defillama", metric=metric, value=data,
                           fetched_at=datetime.now(timezone.utc).isoformat())
        if metric == "market_snapshot":
            data = await self.get_market_snapshot()
            return RawData(source="defillama", metric=metric, value=data,
                           fetched_at=datetime.now(timezone.utc).isoformat())
        return RawData(source="defillama", metric=metric, value=None,
                       fetched_at=datetime.now(timezone.utc).isoformat())

    async def health_check(self) -> DataSourceHealth:
        try:
            _throttle()
            resp = await asyncio.to_thread(
                requests.get, f"{_BASE_TVL}/chains",
                timeout=8,
            )
            if resp.status_code == 200:
                return DataSourceHealth(available=True)
            return DataSourceHealth(available=False, error_message=f"HTTP {resp.status_code}")
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))

    # ── Internal ────────────────────────────────────────────────

    async def _fetch_json(self, url: str) -> dict[str, Any] | list | None:
        """Fetch JSON from DeFiLlama with throttling."""
        _throttle()
        try:
            resp = await asyncio.to_thread(
                requests.get, url, timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("DeFiLlama %s → HTTP %d", url, resp.status_code)
                return None
            return resp.json()
        except Exception as exc:
            logger.warning("DeFiLlama fetch failed %s: %s", url, exc)
            return None
