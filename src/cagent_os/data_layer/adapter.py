"""DataSourceAdapter ABC — all data sources implement this interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class DataSourceHealth:
    available: bool
    latency_ms: float | None = None
    error_message: str | None = None


@dataclass
class RawData:
    source: str
    metric: str
    value: Any
    raw_response: dict[str, Any] | None = None
    fetched_at: str = ""


class StatusSource(ABC):
    """A data provider that appears in the sidebar when registered."""
    name: str = ""
    display_name: str = ""

    @abstractmethod
    async def health_check(self) -> DataSourceHealth:
        ...


class DataSourceAdapter(StatusSource):
    """Uniform interface for all data sources (API, MCP, web scrape, etc.)."""

    tier: int = 1

    @abstractmethod
    async def fetch(self, metric: str, **params: Any) -> RawData:
        ...
