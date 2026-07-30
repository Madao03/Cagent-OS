"""Crypto data plugin — structured on-chain/derivatives/DeFi/sentiment data.

Replaces raw web.fetch scraping with first-class DataLayer adapters.
All capabilities carry explicit caliber metadata (unit / interval / venue / definition).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from cagent_os.plugins.plugin import Plugin, PluginSpec
from cagent_os.plugins.manifests import ToolSpec
from cagent_os.plugins.contracts import ToolTrustLevel, ToolRequest, ToolResult

logger = logging.getLogger(__name__)


class CryptoPlugin(Plugin):
    """Crypto data capabilities backed by free, no-key adapters."""

    def __init__(self) -> None:
        self._defillama = None
        self._fear_greed = None
        self._coinmetrics = None
        self._binance = None
        self._init_adapters()

    def _init_adapters(self) -> None:
        try:
            from cagent_os.data_layer.adapters.defillama_adapter import DefiLlamaAdapter
            self._defillama = DefiLlamaAdapter()
        except Exception:
            logger.warning("DeFiLlama adapter init failed")
        try:
            from cagent_os.data_layer.adapters.fear_greed_adapter import FearGreedAdapter
            self._fear_greed = FearGreedAdapter()
        except Exception:
            logger.warning("FearGreed adapter init failed")
        try:
            from cagent_os.data_layer.adapters.coinmetrics_adapter import CoinMetricsAdapter
            self._coinmetrics = CoinMetricsAdapter()
        except Exception:
            logger.warning("CoinMetrics adapter init failed")
        try:
            from cagent_os.data_layer.adapters.binance_derivatives_adapter import BinanceDerivativesAdapter
            self._binance = BinanceDerivativesAdapter()
        except Exception:
            logger.warning("Binance derivatives adapter init failed")

    def manifest(self) -> PluginSpec:
        capabilities = [
            self._manifest(
                "crypto.onchain.metrics",
                "Get on-chain metrics (MVRV, market cap, chain stats) from Coin Metrics Community. "
                "Free, no API key. MVRV-Z includes explicit stdev window parameter. "
                "Daily frequency. Use for crypto-analysis skill's cycle positioning.",
                {
                    "asset": {"type": "string", "description": "Asset symbol: btc, eth, etc."},
                    "metric": {"type": "string", "description": "mvrv (default) or chain_stats"},
                    "days": {"type": "integer", "description": "Lookback window for MVRV-Z. 0=all history (default, matches public charts). 365=1yr rolling."},
                },
            ),
            self._manifest(
                "crypto.derivatives.funding",
                "Get current funding rate from Binance Futures. "
                "Returns NATIVE 8h rate (not annualized by default). "
                "Single-venue (Binance only) — labeled venue=binance.",
                {
                    "symbol": {"type": "string", "description": "Trading pair: BTCUSDT (default), ETHUSDT, etc."},
                },
            ),
            self._manifest(
                "crypto.derivatives.oi",
                "Get open interest + long/short ratio from Binance Futures. "
                "OI unit=contracts (not USD). Single-venue.",
                {
                    "symbol": {"type": "string", "description": "Trading pair: BTCUSDT (default)"},
                    "include_history": {"type": "boolean", "description": "Include 7d history. Default false."},
                },
            ),
            self._manifest(
                "crypto.defi.tvl",
                "Get DeFi TVL data from DeFiLlama (free, no key). "
                "Returns chain-level TVL ranking + protocol TVL + DEX volume. "
                "Single authoritative source — no cross-validation (like FRED).",
                {
                    "protocol": {"type": "string", "description": "Optional protocol slug (e.g., aave, uniswap). If omitted, returns all chains."},
                },
            ),
            self._manifest(
                "crypto.defi.stablecoins",
                "Get stablecoin supply data from DeFiLlama. "
                "Returns circulating supply (not total minted) for all stablecoins.",
                {},
            ),
            self._manifest(
                "crypto.defi.revenue",
                "Get protocol fees/revenue from DeFiLlama. "
                "⚠️ fees ≠ revenue: fees=what users pay, revenue=what protocol keeps. "
                "Endpoint may return None (known instability). "
                "For P/S calculation, use revenue (not fees).",
                {},
            ),
            self._manifest(
                "crypto.sentiment.fng",
                "Get Fear & Greed Index from alternative.me (free, no key). "
                "Emotional sentiment indicator (0-100). "
                "⚠️ This is a SENTIMENT indicator — must NOT participate in numeric "
                "cross-validation with price/volume data.",
                {
                    "days": {"type": "integer", "description": "History lookback. Default 1 (latest only)."},
                },
            ),
        ]
        return PluginSpec(plugin_id="crypto", capabilities=capabilities)

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        known = {c.capability_id for c in self.manifest().capabilities}
        if capability_id not in known:
            raise KeyError(capability_id)

        def _handler(request: ToolRequest) -> ToolResult:
            content = self._dispatch(capability_id, request.arguments)
            if isinstance(content, dict) and content.get("success") is False:
                return ToolResult(status="error", content=content,
                                  error_code=str(content.get("error", "crypto_error")))
            return ToolResult(status="ok", content=content)

        return _handler

    def _dispatch(self, capability_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if capability_id == "crypto.onchain.metrics":
                return self._handle_onchain(arguments)
            if capability_id == "crypto.derivatives.funding":
                return self._handle_funding(arguments)
            if capability_id == "crypto.derivatives.oi":
                return self._handle_oi(arguments)
            if capability_id == "crypto.defi.tvl":
                return self._handle_tvl(arguments)
            if capability_id == "crypto.defi.stablecoins":
                return self._handle_stablecoins(arguments)
            if capability_id == "crypto.defi.revenue":
                return self._handle_revenue(arguments)
            if capability_id == "crypto.sentiment.fng":
                return self._handle_fng(arguments)
        except Exception as exc:
            logger.exception("Crypto capability %s failed", capability_id)
            return {"success": False, "error": "internal_error", "message": str(exc)}

        return {"success": False, "error": "unknown_capability"}

    # ── Handlers ────────────────────────────────────────────────

    def _handle_onchain(self, arguments: dict) -> dict:
        if not self._coinmetrics:
            return {"success": False, "error": "adapter_unavailable", "message": "CoinMetrics adapter not initialized"}
        asset = str(arguments.get("asset", "btc"))
        metric = str(arguments.get("metric", "mvrv"))
        days = int(arguments.get("days", 0))

        if metric == "chain_stats":
            result = asyncio.run(self._coinmetrics.get_chain_stats(asset=asset))
        else:
            result = asyncio.run(self._coinmetrics.get_mvrv(asset=asset, days=days))

        if not result:
            return {"success": False, "error": "no_data", "message": f"No data for {asset}"}
        return {"success": True, **result}

    def _handle_funding(self, arguments: dict) -> dict:
        if not self._binance:
            return {"success": False, "error": "adapter_unavailable"}
        symbol = str(arguments.get("symbol", "BTCUSDT"))
        result = asyncio.run(self._binance.get_funding_rate(symbol))
        if not result:
            return {"success": False, "error": "no_data", "message": f"No funding rate for {symbol}"}
        return {"success": True, **result}

    def _handle_oi(self, arguments: dict) -> dict:
        if not self._binance:
            return {"success": False, "error": "adapter_unavailable"}
        symbol = str(arguments.get("symbol", "BTCUSDT"))
        include_history = arguments.get("include_history", False)

        result = asyncio.run(self._binance.get_derivatives_snapshot(symbol))
        if include_history:
            history = asyncio.run(self._binance.get_long_short_ratio(symbol, limit=7))
            result["long_short_history_7d"] = history
        return {"success": True, **result}

    def _handle_tvl(self, arguments: dict) -> dict:
        if not self._defillama:
            return {"success": False, "error": "adapter_unavailable"}
        protocol = str(arguments.get("protocol", "")).strip()
        if protocol:
            result = asyncio.run(self._defillama.get_protocol_tvl(protocol))
        else:
            result = asyncio.run(self._defillama.get_market_snapshot())
        if not result:
            return {"success": False, "error": "no_data"}
        return {"success": True, **result}

    def _handle_stablecoins(self, arguments: dict) -> dict:
        if not self._defillama:
            return {"success": False, "error": "adapter_unavailable"}
        result = asyncio.run(self._defillama.get_stablecoins())
        if not result:
            return {"success": False, "error": "no_data"}
        total = sum(s["circulating_usd"] for s in result)
        top10 = sorted(result, key=lambda s: s["circulating_usd"], reverse=True)[:10]
        return {
            "success": True,
            "total_stablecoin_supply_usd": total,
            "top_10": top10,
            "count": len(result),
            "source": "defillama",
            "definition": "circulating supply (peggedUSD), not total minted",
        }

    def _handle_revenue(self, arguments: dict) -> dict:
        if not self._defillama:
            return {"success": False, "error": "adapter_unavailable"}
        result = asyncio.run(self._defillama.get_fees_overview())
        if not result:
            return {
                "success": False,
                "error": "endpoint_unavailable",
                "message": "DeFiLlama /overview/fees returned None (known instability). Use web_search as fallback.",
            }
        return {"success": True, **result}

    def _handle_fng(self, arguments: dict) -> dict:
        if not self._fear_greed:
            return {"success": False, "error": "adapter_unavailable"}
        days = int(arguments.get("days", 1))
        if days > 1:
            result = asyncio.run(self._fear_greed.get_history(days=days))
            return {"success": True, "history": result, "count": len(result),
                    "caliber": "sentiment"}
        else:
            result = asyncio.run(self._fear_greed.get_latest())
            if not result:
                return {"success": False, "error": "no_data"}
            return {"success": True, **result}

    @staticmethod
    def _manifest(
        capability_id: str,
        description: str,
        properties: dict[str, Any],
        *,
        required: list[str] | None = None,
    ) -> ToolSpec:
        return ToolSpec(
            capability_id=capability_id,
            trust_level=ToolTrustLevel.NETWORKED,
            description=description,
            parameters={
                "type": "object",
                "properties": properties,
                **({"required": required} if required else {}),
            },
        )
