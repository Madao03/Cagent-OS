"""Data source adapters — uniform interface for all external data providers."""

from cagent_os.data_layer.adapters.yfinance_adapter import YFinanceAdapter
from cagent_os.data_layer.adapters.fin_skill_adapter import FinSkillAdapter
from cagent_os.data_layer.adapters.akshare_stock_adapter import AkshareStockAdapter
from cagent_os.data_layer.adapters.akshare_futures_adapter import AkshareFuturesAdapter
from cagent_os.data_layer.adapters.fred_adapter import FredAdapter

__all__ = [
    "YFinanceAdapter",
    "FinSkillAdapter",
    "AkshareStockAdapter",
    "AkshareFuturesAdapter",
    "FredAdapter",
]
