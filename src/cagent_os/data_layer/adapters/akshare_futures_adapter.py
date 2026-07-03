"""AKShare futures adapter — domestic commodity/financial futures via Sina.

Covers 5 exchanges × 82 symbols:
  - DCE (大连商品交易所): 铁矿石/豆粕/焦炭/…
  - CZCE (郑州商品交易所): 甲醇/纯碱/…
  - SHFE (上海期货交易所): 螺纹钢/沪金/沪铜/…
  - CFFEX (中国金融期货交易所): 股指期货 IC/IF/IH
  - GFEX (广州期货交易所): 碳酸锂/工业硅

Data: Sina Finance — free, no API key, China direct-connect.

Metric keys:
  - "daily"  → daily OHLCV + volume + open_interest
  - "minute" → 1-min OHLCV + volume + open_interest
  - "quote"  → latest daily close snapshot
"""

from __future__ import annotations

import logging
from typing import Any

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData

logger = logging.getLogger(__name__)


class AkshareFuturesAdapter(DataSourceAdapter):
    """Domestic futures data via akshare → Sina Finance."""

    name = "akshare-futures"
    tier = 1

    # ------------------------------------------------------------------
    # DataSourceAdapter interface
    # ------------------------------------------------------------------

    async def fetch(self, metric: str, **params: Any) -> RawData:
        # "symbols" doesn't need a symbol parameter — skip the guard
        if metric == "symbols":
            try:
                return await self._list_symbols()
            except Exception as exc:
                return RawData(source=self.name, metric=metric, value=None,
                               raw_response={"error": str(exc)})

        symbol = str(params.get("symbol", "")).strip()
        if not symbol:
            return _missing("symbol")

        try:
            if metric == "daily":
                return await self._fetch_daily(symbol, params)
            if metric == "minute":
                return await self._fetch_minute(symbol, params)
            if metric == "quote":
                return await self._fetch_quote(symbol)
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": f"unsupported metric: {metric}"},
            )
        except Exception as exc:
            logger.debug("akshare futures fetch failed: %s/%s — %s", symbol, metric, exc)
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": str(exc)},
            )

    async def health_check(self) -> DataSourceHealth:
        import asyncio
        try:
            await asyncio.to_thread(_ak_import().futures_main_sina, symbol="RB0")
            return DataSourceHealth(available=True)
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))

    # ------------------------------------------------------------------
    # Fetchers
    # ------------------------------------------------------------------

    async def _fetch_daily(self, symbol: str, params: dict) -> RawData:
        import asyncio
        start = str(params.get("start_date", "20250101"))

        df = await asyncio.to_thread(
            _ak_import().futures_main_sina,
            symbol=symbol.upper(),
            start_date=start,
        )
        if df is None or len(df) == 0:
            return RawData(source=self.name, metric="daily", value=None,
                           raw_response={"error": "no data"})

        last = df.iloc[-1].to_dict()
        cols = list(df.columns)
        return RawData(
            source=self.name,
            metric="daily",
            value={
                "date": str(last.get(cols[0], "")),
                "open": float(last.get(cols[1], 0)),
                "high": float(last.get(cols[2], 0)),
                "low": float(last.get(cols[3], 0)),
                "close": float(last.get(cols[4], 0)),
                "volume": int(last.get(cols[5], 0)),
                "open_interest": int(last.get(cols[6], 0)),
                "settle": float(last.get(cols[7], 0)) if len(cols) > 7 else None,
            },
            raw_response={"rows": len(df), "columns": cols},
        )

    async def _fetch_minute(self, symbol: str, params: dict) -> RawData:
        import asyncio
        period = str(params.get("period", "1"))

        df = await asyncio.to_thread(
            _ak_import().futures_zh_minute_sina,
            symbol=symbol.upper(),
            period=period,
        )
        if df is None or len(df) == 0:
            return RawData(source=self.name, metric="minute", value=None,
                           raw_response={"error": "no minute data"})

        last = df.iloc[-1].to_dict()
        return RawData(
            source=self.name,
            metric="minute",
            value={
                "datetime": str(last.get("datetime", "")),
                "open": float(last.get("open", 0)),
                "high": float(last.get("high", 0)),
                "low": float(last.get("low", 0)),
                "close": float(last.get("close", 0)),
                "volume": int(last.get("volume", 0)),
                "hold": int(last.get("hold", 0)),
            },
            raw_response={"rows": len(df), "columns": list(df.columns)},
        )

    async def _fetch_quote(self, symbol: str) -> RawData:
        result = await self._fetch_daily(symbol, {"start_date": "20260101"})
        if result.value:
            result.metric = "quote"
        return result

    async def _list_symbols(self) -> RawData:
        import asyncio

        def _fetch():
            import akshare as ak
            return ak.futures_display_main_sina()

        df = await asyncio.to_thread(_fetch)
        if df is None or len(df) == 0:
            return RawData(source=self.name, metric="symbols", value=[],
                           raw_response={"error": "no symbol data"})
        records = df.to_dict("records")
        symbols = [
            {"symbol": r["symbol"], "name": r["name"], "exchange": r["exchange"]}
            for r in records
        ]
        return RawData(source=self.name, metric="symbols", value=symbols,
                       raw_response={"count": len(symbols)})


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ak_import():
    import akshare as ak
    return ak


def _missing(param: str) -> RawData:
    return RawData(
        source="akshare-futures", metric="unknown", value=None,
        raw_response={"error": f"missing required parameter: {param}"},
    )
