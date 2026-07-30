"""Coin Metrics Community adapter — on-chain fundamentals (free, no key).

Community tier free metrics (verified 2026-07-23):
  ✅ CapMrktCurUSD  — market cap
  ✅ CapMVRVCur      — MVRV ratio (directly available, no need for CapRealUSD)
  ✅ PriceUSD        — spot price
  ✅ SplyCur         — current supply
  ✅ TxCnt           — transaction count
  ✅ AdrActCnt       — active addresses
  ✅ HashRate        — network hash rate
  ❌ CapRealUSD      — requires paid tier
  ❌ DiffLast        — requires paid tier

MVRV-Z is calculated from the CapMVRVCur time series directly.
The stdev window MUST be stored alongside the value.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData

logger = logging.getLogger(__name__)

_BASE = "https://community-api.coinmetrics.io/v4"
_METRICS_ENDPOINT = f"{_BASE}/timeseries/asset-metrics"

# Metrics available on Community tier (verified)
FREE_METRICS = {
    "CapMrktCurUSD", "CapMVRVCur", "PriceUSD",
    "SplyCur", "TxCnt", "AdrActCnt", "HashRate",
}

_THROTTLE_MIN_INTERVAL = 0.5
_last_request_time = 0.0


def _throttle() -> None:
    global _last_request_time
    elapsed = time.perf_counter() - _last_request_time
    if elapsed < _THROTTLE_MIN_INTERVAL:
        time.sleep(_THROTTLE_MIN_INTERVAL - elapsed)
    _last_request_time = time.perf_counter()


class CoinMetricsAdapter(DataSourceAdapter):
    """Coin Metrics Community — on-chain fundamentals (MVRV, price, supply)."""

    tier = 1
    name = "coinmetrics"

    async def get_mvrv(
        self,
        asset: str = "btc",
        days: int = 0,
    ) -> dict[str, Any] | None:
        """Fetch MVRV ratio + market cap and calculate MVRV-Z.

        Classic MVRV-Z formula (LookIntoBitcoin / Glassnode standard):
            Z = (MarketCap - RealizedCap) / stdev(MarketCap - RealizedCap)

        Community tier doesn't provide CapRealUSD, but we can derive it:
            RealizedCap = MarketCap / MVRV

        Thresholds (classic, all-history stdev):
            Z > 7   → market top (historically)
            Z < 0.1 → market bottom (historically)

        Args:
            days: Lookback window. 0 = all history (default, matches public charts).
                  365 = 1-year rolling (different thresholds, must label).
        """
        asset = asset.lower()

        if days == 0:
            # All history — no start_time filter
            params = {
                "assets": asset,
                "metrics": "CapMrktCurUSD,CapMVRVCur",
                "page_size": 10000,
                "frequency": "1d",
            }
            window_label = "all_history"
        else:
            start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
            params = {
                "assets": asset,
                "metrics": "CapMrktCurUSD,CapMVRVCur",
                "start_time": start,
                "page_size": 10000,
                "frequency": "1d",
            }
            window_label = f"{days}d_rolling"

        data = await self._fetch_json(_METRICS_ENDPOINT, params)
        if not data or not data.get("data"):
            return None

        series = data["data"]
        if len(series) < 30:
            logger.warning("CoinMetrics: insufficient data for %s (%d points, need ≥30)",
                           asset, len(series))
            return None

        # Parse series + derive RealizedCap = MarketCap / MVRV
        mvrv_diffs = []  # (MarketCap - RealizedCap) per day
        entries = []

        for point in series:
            mc = self._safe_float(point.get("CapMrktCurUSD"))
            mvrv = self._safe_float(point.get("CapMVRVCur"))
            ts = point.get("time", "")

            if mc is not None and mvrv is not None and mvrv > 0:
                # ★ Derive RealizedCap (Community tier doesn't provide it directly)
                rc = mc / mvrv
                diff = mc - rc  # = mc * (1 - 1/mvrv) = mc * (mvrv - 1) / mvrv
                mvrv_diffs.append(diff)
                entries.append({
                    "date": ts[:10] if ts else "",
                    "market_cap": mc,
                    "realized_cap_derived": rc,
                    "mvrv": mvrv,
                })

        if len(entries) < 30:
            return None

        latest = entries[-1]
        z_score = self._calc_mvrv_z_classic(mvrv_diffs)

        # MVRV percentile: scale-free, dimensionless, cross-cycle comparable.
        # This is the CORRECT metric for cycle positioning — unlike Z percentile
        # which suffers from structural drift (early-era values compressed by
        # denominator dominated by recent trillion-dollar market caps).
        mvrv_raw = [e["mvrv"] for e in entries]
        mvrv_percentile = self._calc_mvrv_raw_percentile(mvrv_raw)

        # Z percentile: kept for reference but has KNOWN ARTIFACT.
        # See _calc_z_percentile docstring for why it's unreliable.
        z_percentile = self._calc_z_percentile(mvrv_diffs)

        # ★ Symbol consistency HARD REJECTION: MVRV > 1 → MV > RV → diff > 0
        # Z < -0.5 in this case means the formula or data is deterministically wrong.
        # This is NOT a "suspicious value" — it's a logical impossibility.
        # Same pattern as filed_date > period_end in LANE 2: hard exclude, not flag.
        if latest["mvrv"] > 1.0 and z_score is not None and z_score < -0.5:
            logger.error(
                "MVRV-Z symbol violation: MVRV=%.4f (>1) but Z=%.4f (<-0.5). "
                "Returning None — formula or data is wrong. Asset=%s",
                latest["mvrv"], z_score, asset,
            )
            return None

        return {
            "asset": asset.upper(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "coinmetrics_community",
            "latest": latest,
            "mvrv_z_variant": z_score,  # variant: uses stdev(diff) as denominator, NOT stdev(MV)
            "mvrv_percentile": mvrv_percentile,  # ★ USE THIS for cycle positioning
            "z_percentile": z_percentile,  # ⚠️ ARTIFACT: structural drift, do NOT use for conclusions
            "zscore_window": window_label,
            "zscore_definition": (
                "MVRV-Z variant = (MarketCap - RealizedCap) / stdev(MarketCap - RealizedCap). "
                "⚠️ This is NOT the standard Glassnode/LookIntoBitcoin formula: "
                "classic uses stdev(MarketCap) as denominator, this uses stdev(diff). "
                "Since MV and RV are highly correlated, stdev(diff) < stdev(MV), "
                "so this variant produces systematically HIGHER values than public charts. "
                "Do NOT compare mvrv_z_variant with Glassnode/LookIntoBitcoin directly. "
                "RealizedCap derived as MarketCap/MVRV (Community tier). "
                f"Window: {window_label}. "
                "USE mvrv_percentile for cycle positioning: <25th = cold, >75th = hot."
            ),
            "history_30d": entries[-30:] if len(entries) >= 30 else entries,
            "confidence": "high",
        }

    async def get_chain_stats(self, asset: str = "btc", days: int = 30) -> dict[str, Any] | None:
        """Fetch basic chain stats: price, supply, tx count, active addresses, hashrate."""
        asset = asset.lower()
        start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

        params = {
            "assets": asset,
            "metrics": "PriceUSD,SplyCur,TxCnt,AdrActCnt,HashRate",
            "start_time": start,
            "page_size": 10000,
            "frequency": "1d",
        }

        data = await self._fetch_json(_METRICS_ENDPOINT, params)
        if not data or not data.get("data"):
            return None

        series = data["data"]
        if not series:
            return None

        latest = series[-1]
        return {
            "asset": asset.upper(),
            "date": latest.get("time", "")[:10],
            "price_usd": self._safe_float(latest.get("PriceUSD")),
            "supply": self._safe_float(latest.get("SplyCur")),
            "tx_count": self._safe_float(latest.get("TxCnt")),
            "active_addresses": self._safe_float(latest.get("AdrActCnt")),
            "hash_rate": self._safe_float(latest.get("HashRate")),
            "source": "coinmetrics_community",
        }

    @staticmethod
    def _calc_mvrv_z_classic(diff_series: list[float]) -> float | None:
        """Classic MVRV-Z: Z = (MarketCap - RealizedCap) / stdev(MarketCap - RealizedCap).

        This is the LookIntoBitcoin / Glassnode standard formula.
        It is a RAW RATIO — NOT a mean-centered z-score.

        diff = MarketCap - RealizedCap (= MarketCap * (MVRV - 1) / MVRV)
        Z = diff / stdev(diff)

        When MVRV > 1, diff > 0, so Z > 0 (symbol consistency guaranteed).

        Thresholds: Z > 7 ≈ historical top, Z < 0.1 ≈ historical bottom.
        Note: these thresholds have structural drift over time (each cycle's
        peak is lower than the previous due to BTC market cap growth).
        Use mvrv_percentile for cross-cycle comparison instead.
        """
        if len(diff_series) < 30:
            return None
        current = diff_series[-1]
        try:
            stdev = statistics.stdev(diff_series)
        except statistics.StatisticsError:
            return None
        if stdev == 0:
            return 0.0
        return round(current / stdev, 4)

    @staticmethod
    def _calc_mvrv_raw_percentile(mvrv_series: list[float]) -> float | None:
        """Calculate where current MVRV ranks historically (0-100 percentile).

        MVRV = MarketCap / RealizedCap is a dimensionless ratio, so it's
        scale-free and cross-cycle comparable. This is the CORRECT metric
        for cycle positioning — unlike Z percentile which has structural drift.

        Interpretation:
          <25th percentile  → historically cold (potential accumulation zone)
          25-75th           → normal range
          >75th percentile  → historically hot (potential distribution zone)
        """
        if len(mvrv_series) < 60:
            return None
        current = mvrv_series[-1]
        below = sum(1 for m in mvrv_series[:-1] if m < current)
        total = len(mvrv_series) - 1
        return round(below / total * 100, 1)

    @staticmethod
    def _calc_z_percentile(diff_series: list[float]) -> float | None:
        """Calculate where the current Z-score ranks historically (0-100 percentile).

        ⚠️ KNOWN ARTIFACT: Z percentile is NOT reliable for cycle positioning.
        Classic Z = (MV-RV) / stdev(MV-RV) uses absolute dollar values.
        Early-era BTC market cap was tiny (billions vs today's trillions),
        so early (MV-RV) values are mechanically small, making early Z values
        cluster near zero. A "75th percentile Z" just means "above the compressed
        early era", not "historically hot".

        Use _calc_mvrv_raw_percentile instead — it's scale-free.
        This method is kept for reference/debugging only.
        """
        if len(diff_series) < 60:  # Need enough history for meaningful percentile
            return None

        mean = statistics.mean(diff_series)
        try:
            stdev = statistics.stdev(diff_series)
        except statistics.StatisticsError:
            return None
        if stdev == 0:
            return 50.0

        # Compute Z for each historical point
        z_values = [(d - mean) / stdev for d in diff_series]
        current_z = z_values[-1]

        # Count how many historical Z values are below current
        below = sum(1 for z in z_values[:-1] if z < current_z)
        total = len(z_values) - 1
        percentile = round(below / total * 100, 1)

        return percentile

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    async def fetch(self, metric: str, **params: Any) -> RawData:
        if metric == "mvrv":
            asset = str(params.get("asset", "btc"))
            days = int(params.get("days", 0))  # 0 = all history
            value = await self.get_mvrv(asset=asset, days=days)
        elif metric == "chain_stats":
            asset = str(params.get("asset", "btc"))
            days = int(params.get("days", 30))
            value = await self.get_chain_stats(asset=asset, days=days)
        else:
            value = await self.get_mvrv()

        return RawData(source="coinmetrics", metric=metric, value=value,
                       fetched_at=datetime.now(timezone.utc).isoformat())

    async def health_check(self) -> DataSourceHealth:
        try:
            _throttle()
            params = {"assets": "btc", "metrics": "PriceUSD", "page_size": 1}
            resp = await asyncio.to_thread(
                requests.get, _METRICS_ENDPOINT, params=params, timeout=10,
            )
            if resp.status_code == 200:
                return DataSourceHealth(available=True)
            return DataSourceHealth(available=False, error_message=f"HTTP {resp.status_code}")
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))

    async def _fetch_json(self, url: str, params: dict) -> dict | None:
        _throttle()
        try:
            resp = await asyncio.to_thread(
                requests.get, url, params=params, timeout=20,
            )
            if resp.status_code != 200:
                logger.warning("CoinMetrics %s → HTTP %d: %s",
                               url, resp.status_code, resp.text[:200])
                return None
            return resp.json()
        except Exception as exc:
            logger.warning("CoinMetrics fetch failed: %s", exc)
            return None

