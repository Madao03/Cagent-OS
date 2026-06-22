from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from cagent_os.plugins.contracts import ToolRequest, ToolResult
from cagent_os.plugins.manifests import PluginSpec


class Plugin(ABC):
    @abstractmethod
    def manifest(self) -> PluginSpec:
        raise NotImplementedError

    @abstractmethod
    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        raise NotImplementedError
