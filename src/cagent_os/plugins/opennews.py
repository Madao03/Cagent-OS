"""Read-only NewsLiquid news tools over the official OpenNews MCP subprocess."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import PluginSpec, ToolSpec
from cagent_os.plugins.plugin import Plugin
from cagent_os.plugins.registry import ToolRegistry


@asynccontextmanager
async def opennews_session():
    env = {
        "OPENNEWS_TOKEN": os.getenv("OPENNEWS_TOKEN", ""),
        "OPENNEWS_API_BASE": "https://ai.6551.io",
        "OPENNEWS_WSS_URL": "wss://ai.6551.io/open/news_wss",
        "PYTHONIOENCODING": "utf-8",
    }
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
        if os.getenv(name):
            env[name] = os.environ[name]
    params = StdioServerParameters(command=os.getenv("OPENNEWS_COMMAND") or "opennews-mcp", env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


class OpenNewsPlugin(Plugin):
    def manifest(self) -> PluginSpec:
        return PluginSpec(
            plugin_id="opennews",
            capabilities=[ToolSpec(
                capability_id="opennews.news",
                trust_level=ToolTrustLevel.NETWORKED,
                description="Search NewsLiquid financial news by keyword, or get the latest news without a keyword.",
                parameters={"type": "object", "properties": {
                    "keyword": {"type": "string", "description": "Keyword such as BTC, LNG, or NVDA"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
                }, "additionalProperties": False},
            )],
        )

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        if capability_id != "opennews.news":
            raise KeyError(capability_id)
        return self._news

    def _news(self, request: ToolRequest) -> ToolResult:
        keyword = request.arguments.get("keyword", "")
        limit = request.arguments.get("limit", 3)
        if not isinstance(keyword, str) or type(limit) is not int or not 1 <= limit <= 10:
            return ToolResult(status="error", error_code="invalid_arguments", content="Invalid keyword or limit.")
        keyword = keyword.strip()
        args = {"limit": limit}
        tool = "get_latest_news"
        if keyword:
            tool = "search_news"
            args["keyword"] = keyword

        async def query():
            async with opennews_session() as session:
                result = await session.call_tool(tool, args)
                if result.isError or not result.content:
                    raise ValueError("OpenNews tool call failed")
                return json.loads(result.content[0].text)

        try:
            payload = asyncio.run(asyncio.wait_for(query(), timeout=45))
        except Exception:
            return ToolResult(status="error", error_code="opennews_unavailable",
                              content="OpenNews MCP unavailable. Check OPENNEWS_COMMAND and connectivity.")
        if not isinstance(payload, dict) or not payload.get("success"):
            return ToolResult(status="error", error_code="opennews_query_failed",
                              content="OpenNews query failed. Check token, subscription and service availability.")
        return ToolResult(status="ok", content=payload)


def register_opennews(registry: ToolRegistry) -> None:
    if os.getenv("OPENNEWS_TOKEN"):
        registry.register_plugin(OpenNewsPlugin())
