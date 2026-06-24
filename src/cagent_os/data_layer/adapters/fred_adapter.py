"""FRED (Federal Reserve Economic Data) adapter — free tier 1 data source.

Provides access to 800,000+ US and international economic time series
from the Federal Reserve Bank of St. Louis. Fills critical gaps in
short-term macro analysis: ONRRP, TGA, bank reserves, Treasury yields,
employment structure, and inflation data.

Rate limit: 120 requests/minute. No API key approval needed.
Docs: https://fred.stlouisfed.org/docs/api/fred/
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData

logger = logging.getLogger(__name__)

# -- Key FRED series for macro analysis ---------------------------------
# Organized by category matching the macro-analysis skill framework.

FRED_SERIES: dict[str, dict[str, str]] = {
    # --- Short-term: liquidity & funding (our biggest gap!) ---
    "onrrp": {
        "series_id": "RRPONTSYD",
        "description": "Overnight Reverse Repurchase Agreements (ON RRP) — $B, daily",
        "unit": "Billions of USD",
        "frequency": "daily",
    },
    "tga": {
        "series_id": "WDTGAL",
        "description": "Treasury General Account (TGA) — $M, weekly (Wed)",
        "unit": "Millions of USD",
        "frequency": "weekly",
    },
    "bank_reserves": {
        "series_id": "TOTRESNS",
        "description": "Total Reserves of Depository Institutions — $B, monthly",
        "unit": "Billions of USD",
        "frequency": "monthly",
    },
    "fed_balance_sheet": {
        "series_id": "WALCL",
        "description": "Federal Reserve Total Assets — $M, weekly (Wed)",
        "unit": "Millions of USD",
        "frequency": "weekly",
    },
    # --- Treasury yields ---
    "treasury_3m": {
        "series_id": "DGS3MO",
        "description": "3-Month Treasury Constant Maturity Rate — %, daily",
        "unit": "Percent",
        "frequency": "daily",
    },
    "treasury_6m": {
        "series_id": "DGS6MO",
        "description": "6-Month Treasury Constant Maturity Rate — %, daily",
        "unit": "Percent",
        "frequency": "daily",
    },
    "treasury_1y": {
        "series_id": "DGS1",
        "description": "1-Year Treasury Constant Maturity Rate — %, daily",
        "unit": "Percent",
        "frequency": "daily",
    },
    "treasury_2y": {
        "series_id": "DGS2",
        "description": "2-Year Treasury Constant Maturity Rate — %, daily",
        "unit": "Percent",
        "frequency": "daily",
    },
    "treasury_10y": {
        "series_id": "DGS10",
        "description": "10-Year Treasury Constant Maturity Rate — %, daily",
        "unit": "Percent",
        "frequency": "daily",
    },
    "yield_spread_10y2y": {
        "series_id": "T10Y2Y",
        "description": "10-Year minus 2-Year Treasury Spread — %, daily",
        "unit": "Percent",
        "frequency": "daily",
    },
    # --- Employment ---
    "nonfarm_payrolls": {
        "series_id": "PAYEMS",
        "description": "All Employees, Total Nonfarm — thousands, monthly",
        "unit": "Thousands",
        "frequency": "monthly",
    },
    "unemployment_rate": {
        "series_id": "UNRATE",
        "description": "Civilian Unemployment Rate — %, monthly",
        "unit": "Percent",
        "frequency": "monthly",
    },
    "jolts_openings": {
        "series_id": "JTSJOL",
        "description": "Job Openings: Total Nonfarm (JOLTS) — thousands, monthly",
        "unit": "Thousands",
        "frequency": "monthly",
    },
    "participation_rate": {
        "series_id": "CIVPART",
        "description": "Labor Force Participation Rate — %, monthly",
        "unit": "Percent",
        "frequency": "monthly",
    },
    "avg_hourly_earnings": {
        "series_id": "AHETPI",
        "description": "Avg Hourly Earnings of All Private Employees — $/hour, monthly",
        "unit": "Dollars per Hour",
        "frequency": "monthly",
    },
    # --- Inflation ---
    "cpi": {
        "series_id": "CPIAUCSL",
        "description": "CPI for All Urban Consumers — index 1982-84=100, monthly",
        "unit": "Index",
        "frequency": "monthly",
    },
    "ppi": {
        "series_id": "PPIACO",
        "description": "PPI All Commodities — index 1982=100, monthly",
        "unit": "Index",
        "frequency": "monthly",
    },
    "core_pce": {
        "series_id": "PCEPILFE",
        "description": "Core PCE Price Index (excl Food & Energy) — index 2017=100, monthly",
        "unit": "Index",
        "frequency": "monthly",
    },
    # --- GDP ---
    "gdp": {
        "series_id": "GDP",
        "description": "Gross Domestic Product — $B, quarterly",
        "unit": "Billions of USD",
        "frequency": "quarterly",
    },
    # --- Money supply ---
    "m1": {
        "series_id": "M1SL",
        "description": "M1 Money Supply — $B, monthly",
        "unit": "Billions of USD",
        "frequency": "monthly",
    },
    "m2": {
        "series_id": "M2SL",
        "description": "M2 Money Supply — $B, monthly",
        "unit": "Billions of USD",
        "frequency": "monthly",
    },
}


class FredAdapter(DataSourceAdapter):
    """FRED economic data adapter.

    Usage:
        adapter = FredAdapter(api_key="your-fred-key")
        raw = await adapter.fetch("onrrp")
        # raw.value → 6484 (latest ONRRP in $B)
        # raw.raw_response → {"series_id": "RRPONTSYD", "observations": [...]}

    Also supports fetching arbitrary series by ID:
        raw = await adapter.fetch("custom", series_id="GDPC1")
    """

    name = "fred"
    tier = 1

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._base_url = "https://api.stlouisfed.org/fred"

    # ------------------------------------------------------------------
    # DataSourceAdapter interface
    # ------------------------------------------------------------------

    async def fetch(self, metric: str, **params: Any) -> RawData:
        """Fetch a FRED data series.

        Args:
            metric: Named metric from FRED_SERIES (e.g. "onrrp", "cpi"),
                    or "custom" with series_id kwarg for arbitrary series.
            **params: Optional overrides:
                - series_id: Override the default series ID
                - limit: Number of observations (default 1 = latest)
                - sort_order: "desc" (default) or "asc"
                - observation_start: YYYY-MM-DD filter
                - observation_end: YYYY-MM-DD filter

        Returns:
            RawData with value = latest observation value as float (or None).
        """
        # Resolve series ID
        if metric == "custom":
            series_id = params.get("series_id", "")
        elif metric in FRED_SERIES:
            series_id = FRED_SERIES[metric]["series_id"]
        else:
            # Try as a raw series ID directly
            series_id = metric

        if not series_id:
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": "no series_id provided"},
            )

        limit = int(params.get("limit", 1))
        sort_order = params.get("sort_order", "desc")

        url = (
            f"{self._base_url}/series/observations"
            f"?series_id={series_id}"
            f"&api_key={self._api_key}"
            f"&file_type=json"
            f"&limit={limit}"
            f"&sort_order={sort_order}"
        )
        if params.get("observation_start"):
            url += f"&observation_start={params['observation_start']}"
        if params.get("observation_end"):
            url += f"&observation_end={params['observation_end']}"

        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            observations = data.get("observations", [])
            if not observations:
                return RawData(
                    source=self.name, metric=metric, value=None,
                    raw_response={"series_id": series_id, "error": "no observations returned"},
                )

            # Extract latest non-missing value
            latest_value = None
            latest_date = ""
            for obs in observations:
                val = obs.get("value", ".")
                if val not in (".", "N/A", None, ""):
                    try:
                        latest_value = float(val)
                    except (ValueError, TypeError):
                        latest_value = val  # keep as string if not numeric
                    latest_date = obs.get("date", "")
                    break

            return RawData(
                source=self.name,
                metric=metric,
                value=latest_value,
                raw_response={
                    "series_id": series_id,
                    "latest_date": latest_date,
                    "unit": FRED_SERIES.get(metric, {}).get("unit", ""),
                    "description": FRED_SERIES.get(metric, {}).get("description", ""),
                    "frequency": FRED_SERIES.get(metric, {}).get("frequency", ""),
                    "observations_count": data.get("count", 0),
                },
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )
        except requests.RequestException as exc:
            logger.warning("FRED fetch failed: %s — %s", series_id, exc)
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"series_id": series_id, "error": str(exc)},
            )

    async def health_check(self) -> DataSourceHealth:
        """Ping FRED with a known series to verify API is reachable."""
        import time
        try:
            start = time.monotonic()
            url = (
                f"{self._base_url}/series/observations"
                f"?series_id=T10Y2Y"
                f"&api_key={self._api_key}"
                f"&file_type=json&limit=1&sort_order=desc"
            )
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("observations"):
                latency_ms = (time.monotonic() - start) * 1000
                return DataSourceHealth(available=True, latency_ms=latency_ms)
            return DataSourceHealth(available=False, error_message="FRED returned empty observations")
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def list_available_metrics(self) -> list[dict[str, str]]:
        """Return all named metrics with descriptions."""
        return [
            {
                "metric": key,
                "series_id": val["series_id"],
                "description": val["description"],
                "frequency": val["frequency"],
            }
            for key, val in FRED_SERIES.items()
        ]

    async def fetch_series_info(self, series_id: str) -> dict[str, Any] | None:
        """Get metadata for an arbitrary FRED series."""
        url = (
            f"{self._base_url}/series"
            f"?series_id={series_id}"
            f"&api_key={self._api_key}"
            f"&file_type=json"
        )
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            ser = data.get("seriess", [{}])[0]
            return {
                "id": ser.get("id"),
                "title": ser.get("title"),
                "frequency": ser.get("frequency"),
                "units": ser.get("units"),
                "popularity": ser.get("popularity"),
                "notes": ser.get("notes", ""),
            }
        except Exception:
            return None
