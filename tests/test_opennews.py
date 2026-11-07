from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cagent_os.plugins.contracts import ToolRequest
from cagent_os.plugins.opennews import register_opennews
from cagent_os.plugins.registry import ToolRegistry


@pytest.mark.parametrize("args,tool", [({}, "get_latest_news"), ({"keyword": " LNG "}, "search_news")])
@pytest.mark.parametrize("error_field", ["is_error", "isError"])
def test_read_only_news_dispatch(monkeypatch, args, tool, error_field):
    registry = ToolRegistry()
    monkeypatch.delenv("OPENNEWS_TOKEN", raising=False)
    register_opennews(registry)
    assert not registry.default_enabled_tool_ids()
    monkeypatch.setenv("OPENNEWS_TOKEN", "test")
    register_opennews(registry)
    assert registry.default_enabled_tool_ids() == ["opennews.news"]
    call = AsyncMock(return_value=SimpleNamespace(**{error_field: False}, content=[
        SimpleNamespace(text='{"success":true,"data":[{"link":"https://example.com/article"}]}')
    ]))

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(call_tool=call)

    monkeypatch.setattr("cagent_os.plugins.opennews.opennews_session", session)
    result = registry.resolve("opennews.news")(ToolRequest("opennews.news", args))
    call.assert_awaited_once_with(tool, {"limit": 3, **({"keyword": "LNG"} if args else {})})
    assert result.status == "ok" and result.content["data"][0]["link"]
