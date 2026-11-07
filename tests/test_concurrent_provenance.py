from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

from cagent_os.agents.run_engine import AgentRuntime, _AgentRunState
from cagent_os.plugins.contracts import ToolResult
from cagent_os.plugins.executor import ToolDispatcher
from cagent_os.provenance import FactRegistry


def test_concurrent_tool_results_only_register_with_their_own_run():
    both_running = Barrier(2)

    def handler(request):
        both_running.wait(timeout=3)
        return ToolResult(status="ok", content=request.arguments["price"])

    tools = Mock()
    tools.resolve.return_value = handler
    default_registry = FactRegistry()
    dispatcher = ToolDispatcher(registry=tools, fact_registry=default_registry)
    runtime = AgentRuntime(conversation_service=Mock(), event_store=Mock(),
                           llm_backend=Mock(), capability_executor=dispatcher)

    def run_tool(ticker, price):
        state = _AgentRunState()
        result = runtime._execute_tool_once(
            conversation_id=ticker, user_id=ticker, tool_call_id="call",
            capability_id="quote", arguments={"ticker": ticker, "price": price}, state=state,
        )
        assert result.events[0].type == "run.tool_completed"
        assert len(result.events[0].data["_fact_refs"]) == 1
        return [fact.value for fact in state.fact_registry.facts]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_tool, "AAA", 101)
        second = pool.submit(run_tool, "BBB", 202)
        assert first.result() == [101]
        assert second.result() == [202]
    assert default_registry.facts == []
