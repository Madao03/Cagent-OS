"""MCP tool discovery — read server list from config, discover tools."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class MCPServerRegistry:
    def __init__(self, config_path: str | Path) -> None:
        self._config_path = Path(config_path)

    def load_configs(self) -> list[dict]:
        if not self._config_path.exists():
            logger.warning("MCP config not found: %s", self._config_path)
            return []
        with open(self._config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("servers", [])
