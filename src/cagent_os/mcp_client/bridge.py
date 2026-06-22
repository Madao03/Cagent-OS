"""MCP bridge — auto-register discovered MCP tools as Capabilities.

When an MCP server connects and its tools are discovered, this bridge
wraps each MCP tool as a Pydantic-validated capability and registers
it with ToolRegistry. After that, the LLM sees it like any other
tool — the MCP origin is transparent.
"""

from __future__ import annotations

import logging
from typing import Any

from cagent_os.mcp_client.session import MCPSessionManager

logger = logging.getLogger(__name__)


class MCPBridge:
    """Discover tools from connected MCP servers, register them as capabilities."""

    def __init__(self, session_manager: MCPSessionManager) -> None:
        self._sessions = session_manager

    async def discover_and_register(
        self,
        server_name: str,
        registry: Any,  # ToolRegistry — avoid circular import
    ) -> int:
        """Discover tools from one MCP server, register each as a capability.

        Returns the number of tools registered.
        """
        tools = await self._sessions.list_tools(server_name)
        count = 0
        for tool in tools:
            capability_id = f"mcp.{server_name}.{tool.name}"

            async def _handler(
                _kwargs: Any,
                _server: str = server_name,
                _tool: str = tool.name,
            ) -> Any:
                return await self._sessions.call_tool(_server, _tool, _kwargs)

            registry.register(
                capability_id=capability_id,
                handler=_handler,
                manifest=None,  # built from MCP tool schema
                default_enabled=True,
            )
            count += 1
            logger.info("Registered MCP capability: %s", capability_id)
        return count
