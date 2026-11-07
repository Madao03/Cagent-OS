import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cagent_os.data_layer import DataLayer
from cagent_os.mcp_client.session import MCPSessionManager
from cagent_os.plugins.opennews import register_opennews
from cagent_os.plugins.registry import ToolRegistry


def test_opennews_registration_supplies_sidebar_health(monkeypatch):
    monkeypatch.setenv("OPENNEWS_TOKEN", "test")
    registry = ToolRegistry()
    register_opennews(registry)
    session = SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=[
        SimpleNamespace(name="get_latest_news"), SimpleNamespace(name="search_news")
    ])))

    @asynccontextmanager
    async def connect():
        yield session

    monkeypatch.setattr("cagent_os.plugins.opennews.opennews_session", connect)
    status = asyncio.run(DataLayer().health_check_all(registry.status_sources.values()))
    assert status["opennews"].available
    assert registry.status_sources["opennews"].display_name == "NewsLiquid OpenNews"
    session.list_tools.assert_awaited_once()


def test_new_enabled_mcp_server_is_discovered_without_ui_changes():
    manager = MCPSessionManager([{"name": "future-provider"}, {"name": "disabled", "enabled": False}])
    sources = manager.status_sources()
    assert [source.display_name for source in sources] == ["future-provider"]
    assert not asyncio.run(sources[0].health_check()).available
