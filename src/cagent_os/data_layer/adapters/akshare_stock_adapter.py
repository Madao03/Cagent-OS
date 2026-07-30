"""AKShare stock adapter — A-shares, HK stocks, US stocks via Sina.

Covers:
  - A-shares (上海/深圳): daily OHLCV + 1-minute intraday
  - HK stocks: daily OHLCV
  - US stocks: daily OHLCV (via stock_us_daily, Sina Finance US channel)
  - US stock indices (Nasdaq, S&P 500, Dow Jones)

All data from Sina Finance — free, no API key, China direct-connect
(no VPN needed).  East Money source is NOT used (WAF blocks Python).

Metric keys:
  - "daily"  → daily OHLCV + volume + amount
  - "minute" → 1-minute OHLCV + volume + amount (A-shares only)
  - "quote"  → latest close price snapshot
"""

from __future__ import annotations

import logging
from typing import Any

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData

logger = logging.getLogger(__name__)

# Market prefix mapping for Sina API
_SH_SYMBOLS = {"600", "601", "603", "605"}  # 上海交易所前缀


class AkshareStockAdapter(DataSourceAdapter):
    """A-share & HK stock data via akshare → Sina Finance."""

    name = "akshare-stock"
    tier = 1

    # ------------------------------------------------------------------
    # DataSourceAdapter interface
    # ------------------------------------------------------------------

    async def fetch(self, metric: str, **params: Any) -> RawData:
        ticker = str(params.get("ticker", "")).strip()
        if not ticker:
            return _missing("ticker")

        try:
            if metric == "daily":
                return await self._fetch_daily(ticker, params)
            if metric == "minute":
                return await self._fetch_minute(ticker)
            if metric == "quote":
                return await self._fetch_quote(ticker)
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": f"unsupported metric: {metric}"},
            )
        except Exception as exc:
            logger.debug("akshare stock fetch failed: %s/%s — %s", ticker, metric, exc)
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": str(exc)},
            )

    async def health_check(self) -> DataSourceHealth:
        import asyncio
        try:
            await asyncio.to_thread(
                _ak_import().stock_zh_a_daily,
                symbol="sh600519",
                start_date="20260701",
                end_date="20260703",
                adjust="qfq",
            )
            return DataSourceHealth(available=True)
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Fetchers
    # ------------------------------------------------------------------

    async def _fetch_daily(self, ticker: str, params: dict) -> RawData:
        import asyncio
        market = str(params.get("market", "")).lower()
        start = str(params.get("start_date", "20250101"))
        end = str(params.get("end_date", ""))

        if market == "us":
            # US stocks via Sina Finance US channel
            df = await asyncio.to_thread(
                _ak_import().stock_us_daily,
                symbol=ticker,
                adjust="qfq",
            )
        elif market == "hk":
            df = await asyncio.to_thread(
                _ak_import().stock_hk_daily,
                symbol=ticker,
                adjust="qfq",
            )
        else:
            # A-share
            symbol = _to_sina_symbol(ticker, "sh" if _is_shanghai(ticker) else "sz")
            df = await asyncio.to_thread(
                _ak_import().stock_zh_a_daily,
                symbol=symbol,
                start_date=start,
                end_date=end or None,
                adjust="qfq",
            )

        if df is None or len(df) == 0:
            return RawData(source=self.name, metric="daily", value=None,
                           raw_response={"error": "no data"})

        # Filter date range (Sina returns datetime.date objects)
        from datetime import date as _date
        if "date" in df.columns:
            if start:
                try:
                    start_d = _date.fromisoformat(start)
                    df = df[df["date"] >= start_d]
                except (ValueError, TypeError):
                    pass
            if end:
                try:
                    end_d = _date.fromisoformat(end)
                    df = df[df["date"] <= end_d]
                except (ValueError, TypeError):
                    pass

        if len(df) == 0:
            return RawData(source=self.name, metric="daily", value=None,
                           raw_response={"error": "no data in range"})

        last = df.iloc[-1].to_dict()
        return RawData(
            source=self.name,
            metric="daily",
            value={
                "date": str(last.get("date", "")),
                "open": float(last.get("open", 0)),
                "high": float(last.get("high", 0)),
                "low": float(last.get("low", 0)),
                "close": float(last.get("close", 0)),
                "volume": float(last.get("volume", 0)),
                "amount": float(last.get("amount", 0)) if "amount" in last else None,
            },
            raw_response={"rows": len(df), "columns": list(df.columns)},
        )

    async def _fetch_minute(self, ticker: str) -> RawData:
        import asyncio
        symbol = _to_sina_symbol(ticker, "sh" if _is_shanghai(ticker) else "sz")
        df = await asyncio.to_thread(
            _ak_import().stock_zh_a_minute,
            symbol=symbol,
            period="1",
        )
        if df is None or len(df) == 0:
            return RawData(source=self.name, metric="minute", value=None,
                           raw_response={"error": "no minute data"})

        last = df.iloc[-1].to_dict()
        return RawData(
            source=self.name,
            metric="minute",
            value={
                "time": str(last.get("day", "")),
                "open": float(last.get("open", 0)),
                "high": float(last.get("high", 0)),
                "low": float(last.get("low", 0)),
                "close": float(last.get("close", 0)),
                "volume": float(last.get("volume", 0)),
                "amount": float(last.get("amount", 0)),
            },
            raw_response={"rows": len(df), "columns": list(df.columns)},
        )

    async def _fetch_quote(self, ticker: str) -> RawData:
        """Snapshot: just the latest daily close."""
        result = await self._fetch_daily(ticker, {"start_date": "20260101"})
        if result.value:
            return RawData(
                source=self.name, metric="quote", value=result.value,
                raw_response=result.raw_response,
            )
        return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ak_import():
    import akshare as ak
    return ak


def _is_shanghai(ticker: str) -> bool:
    """Detect Shanghai exchange by ticker prefix (6xx = 上海)."""
    return any(ticker.startswith(p) for p in _SH_SYMBOLS)


def _to_sina_symbol(ticker: str, exchange: str) -> str:
    """Convert plain ticker to Sina symbol: 600519 → sh600519."""
    if ticker.startswith("sh") or ticker.startswith("sz"):
        return ticker
    return f"{exchange}{ticker}"


def _missing(param: str) -> RawData:
    return RawData(
        source="akshare-stock", metric="unknown", value=None,
        raw_response={"error": f"missing required parameter: {param}"},
    )
