"""MCP session management — multi-transport connect, reconnect, heartbeat.

Uses Anthropic's official `mcp` Python SDK. Do NOT hand-roll SSE/JSON-RPC.
"""

from __future__ import annotations

import logging
import os
from contextlib import AsyncExitStack

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)


class MCPSessionManager:
    """Manages MCP connections for all configured servers.

    Supports SSE and streamable-http transports. Servers configured with
    stdio + alt_transport will use the alt_transport on platforms where
    subprocess spawning isn't available (e.g. Windows).

    Auth is read from config fields: auth_header, auth_prefix, auth_env.
    The env var named by auth_env is read at connect time.
    """

    def __init__(self, server_configs: list[dict]) -> None:
        self._configs = server_configs
        self._sessions: dict[str, ClientSession] = {}
        self._stacks: dict[str, AsyncExitStack] = {}

    async def connect_all(self) -> None:
        for cfg in self._configs:
            if not cfg.get("enabled", True):
                continue
            name = cfg["name"]
            transport, url = self._resolve_transport(cfg)
            if url is None:
                logger.warning("MCP skip %s: no URL resolved", name)
                continue

            try:
                stack = AsyncExitStack()
                headers = self._build_headers(cfg)
                read, write = await self._connect_transport(
                    stack, transport, url, headers
                )
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self._sessions[name] = session
                self._stacks[name] = stack
                logger.info("MCP connected: %s (%s via %s)", name, url, transport)
            except Exception:
                logger.exception("MCP connection failed: %s (%s)", name, url)

    # ------------------------------------------------------------------
    # Transport resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_transport(cfg: dict) -> tuple[str | None, str | None]:
        """Resolve (transport_type, url) from config.

        Priority: direct SSE url > alt_transport > direct url.
        """
        url = cfg.get("url")
        transport = cfg.get("transport", "").upper()

        if url and transport == "SSE":
            return "SSE", url

        alt = cfg.get("alt_transport")
        if alt and alt.get("url"):
            alt_type = alt.get("type", "SSE").replace("-", "_")
            return alt_type, alt["url"]

        if url:
            return transport, url

        return None, None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    @staticmethod
    def _build_headers(cfg: dict) -> dict[str, str] | None:
        """Build auth headers from config, reading the key from env."""
        header_name = cfg.get("auth_header")
        if not header_name:
            return None
        env_var = cfg.get("auth_env", "")
        key = os.getenv(env_var, "")
        if not key:
            logger.warning("MCP auth: %s is not set for %s", env_var, cfg["name"])
            return None
        prefix = cfg.get("auth_prefix", "")
        value = f"{prefix}{key}"
        return {header_name: value}

    # ------------------------------------------------------------------
    # Transport open
    # ------------------------------------------------------------------

    @staticmethod
    async def _connect_transport(
        stack: AsyncExitStack,
        transport: str,
        url: str,
        headers: dict[str, str] | None = None,
    ):
        """Open the transport stream, registered with the given exit stack.

        streamable-http returns 3 values (read, write, session_id_cb);
        sse returns 2. The session_id callback is discarded — it's only
        needed for session resumption, which we don't use yet.
        """
        transport = transport.lower().replace("-", "_")
        if transport in ("sse",):
            return await stack.enter_async_context(sse_client(url, headers=headers))
        if transport in ("streamable_http", "streamablehttp"):
            # streamable-http uses httpx.AsyncClient for auth
            client = httpx.AsyncClient(headers=headers) if headers else None
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(url, http_client=client)
            )
            return read, write
        raise ValueError(f"Unsupported MCP transport: {transport}")

    # ------------------------------------------------------------------
    # Tool API
    # ------------------------------------------------------------------

    async def call_tool(
        self, server: str, tool_name: str, arguments: dict
    ) -> object:
        session = self._sessions.get(server)
        if not session:
            raise RuntimeError(f"MCP server not connected: {server}")
        result = await session.call_tool(tool_name, arguments)
        return result

    async def list_tools(self, server: str) -> list:
        session = self._sessions.get(server)
        if not session:
            raise RuntimeError(f"MCP server not connected: {server}")
        tools_result = await session.list_tools()
        return list(tools_result.tools)

    async def close_all(self) -> None:
        for name, stack in self._stacks.items():
            try:
                await stack.aclose()
            except BaseException:
                # streamable-http sends DELETE on close; if the event loop is
                # already shutting down this may fail with CancelledError.
                # Suppress and move on — the session is closed regardless.
                logger.debug("Non-critical error closing MCP session: %s", name)
        self._sessions.clear()
        self._stacks.clear()
