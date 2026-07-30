"""Fear & Greed Index adapter — alternative.me (free, no key).

Emotional sentiment indicator (0-100). NOT a price indicator — must not
participate in numeric cross-validation with price/volume data.

Daily update (UTC 00:00). Historical data available since 2018-02.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import requests

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData

logger = logging.getLogger(__name__)

_BASE = "https://api.alternative.me"
_ENDPOINT = f"{_BASE}/fng/"  # MUST end with trailing slash


class FearGreedAdapter(DataSourceAdapter):
    """alternative.me Fear & Greed Index."""

    tier = 1
    name = "fear_greed"

    async def get_latest(self) -> dict[str, Any] | None:
        """Current fear & greed index."""
        data = await self._fetch_json(params={"limit": 1})
        if not data or not data.get("data"):
            return None
        entry = data["data"][0]
        return self._parse_entry(entry)

    async def get_history(self, days: int = 30) -> list[dict[str, Any]]:
        """Historical fear & greed index (most recent first)."""
        data = await self._fetch_json(params={"limit": days})
        if not data or not data.get("data"):
            return []
        return [self._parse_entry(e) for e in data["data"]]

    @staticmethod
    def _parse_entry(entry: dict) -> dict[str, Any]:
        """Parse API entry with explicit caliber."""
        ts = int(entry.get("timestamp", 0))
        value = int(entry.get("value", 0))
        return {
            "value": value,
            "classification": entry.get("value_classification", ""),
            "timestamp": ts,
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
            "source": "alternative.me",
            "caliber": "sentiment",  # NOT price — do not cross-validate with price
        }

    async def fetch(self, metric: str, **params: Any) -> RawData:
        if metric == "latest":
            value = await self.get_latest()
        elif metric == "history":
            days = int(params.get("days", 30))
            value = await self.get_history(days=days)
        else:
            value = await self.get_latest()
        return RawData(source="fear_greed", metric=metric, value=value,
                       fetched_at=datetime.now(timezone.utc).isoformat())

    async def health_check(self) -> DataSourceHealth:
        try:
            resp = await asyncio.to_thread(
                requests.get, _ENDPOINT, params={"limit": 1}, timeout=8,
            )
            if resp.status_code == 200:
                return DataSourceHealth(available=True)
            return DataSourceHealth(available=False, error_message=f"HTTP {resp.status_code}")
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))

    async def _fetch_json(self, params: dict | None = None) -> dict | None:
        try:
            resp = await asyncio.to_thread(
                requests.get, _ENDPOINT, params=params or {}, timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("Fear&Greed HTTP %d", resp.status_code)
                return None
            return resp.json()
        except Exception as exc:
            logger.warning("Fear&Greed fetch failed: %s", exc)
            return None
