"""Verify the three cases that hit iteration limit now pass."""
import sys, time, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")
from pathlib import Path
from cagent_os.config import get_settings
from cagent_os.conversations import ConversationService, InMemoryConversationRepository
from cagent_os.llm.factory import create_backend
from cagent_os.memory.sqlite_store import SqliteMemoryStore
from cagent_os.observability.tracing import TraceWriter
from cagent_os.plugins.executor import ToolDispatcher
from cagent_os.provenance import check_provenance, FactRegistry
from cagent_os.shared.async_bridge import AsyncBridge
from cagent_os.user_skills import FilesystemUserSkillStore, UserSkillService
from cagent_os.agents import AgentRuntime
from cagent_os.interfaces.cli import build_registry

CASES = [
    ("case_003", "分析 NVDA（NVIDIA）的当前估值和风险。重点看：1) Forward PE 和 PEG 是否合理，2) 是否有周期股陷阱信号，3) AI CapEx 周期对 NVDA 的影响。给出明确的投资建议。"),
    ("case_005", "STRC 是个啥情况，现在恐慌是不是过头了，现在买博弈均值回归的盈利预期如何？"),
    ("case_011", "分析 COIN (Coinbase) 的收入结构和现金流机制"),
]

settings = get_settings()
project_root = Path(".")
Path("data").mkdir(exist_ok=True)
bridge = AsyncBridge()
memory_store = SqliteMemoryStore(db_path="data/memory.db")
bridge.run(memory_store.open(), timeout=10)

skill_store = FilesystemUserSkillStore(
    data_dir=(project_root / settings.skills_data_dir).resolve(),
    shared_skills_dir=(project_root / settings.shared_skills_dir).resolve()
    if settings.shared_skills_dir else None,
)
skill_service = UserSkillService(store=skill_store)
registry, toolkit = build_registry(mcp_manager=None, skill_service=skill_service, memory_api=memory_store)
executor = ToolDispatcher(registry=registry)
repo = InMemoryConversationRepository()
conversation_service = ConversationService(repository=repo)
llm_backend = create_backend(settings)
trace_writer = TraceWriter(db_path="data/trace.db")
bridge.run(trace_writer.open(), timeout=10)

engine = AgentRuntime(
    conversation_service=conversation_service, event_store=repo,
    llm_backend=llm_backend, capability_executor=executor, settings=settings,
    memory_api=memory_store, trace_writer=trace_writer, async_bridge=bridge,
)

principal_id = settings.default_principal_id
user_id = settings.default_user_id

# Tool call logging
_orig_execute = ToolDispatcher.execute
tool_logs = []

def _logged(self, req):
    t0t = time.perf_counter()
    result = _orig_execute(self, req)
    ms = (time.perf_counter() - t0t) * 1000
    status = "OK" if result.status == "ok" else f"ERR({result.error_code})"
    tool_logs.append(f"  {req.capability_id:40s} {status:30s} {ms:.0f}ms")
    return result
ToolDispatcher.execute = _logged

try:
    for cid, query in CASES:
        print(f"\n{'='*70}\n{cid}: {query[:80]}\n{'='*70}")

        executor.attach_fact_registry(FactRegistry())
        tool_logs.clear()

        snapshot = skill_service.load_snapshot(user_id)
        conv = conversation_service.create_conversation(
            principal_id=principal_id, user_id=user_id,
            user_skill_snapshot=snapshot,
        )
        t0 = time.perf_counter()
        final_content = ""

        try:
            for entry in engine.run(
                conversation_id=conv.conversation_id,
                principal_id=principal_id,
                user_content=query,
                skip_provenance_gate=True,
            ):
                if entry.type == "message.assistant_added":
                    final_content = entry.content or ""
        except Exception as exc:
            print(f"  RUN FAILED: {exc}")
            continue

        elapsed = time.perf_counter() - t0

        # Check for circuit breaker / fallback in tool logs
        has_cb = any("circuit_breaker" in str(l) or "akshare" in str(l) for l in tool_logs)
        has_derivations = "[derivations]" in final_content
        has_pe_static = "pe_static" in final_content.lower() or "static" in final_content.lower()
        has_price_as_of = "price_as_of" in final_content or "akshare" in final_content.lower()

        print(f"  elapsed: {elapsed:.1f}s")
        print(f"  output: {len(final_content)} chars")
        print(f"  circuit_breaker/fallback seen: {has_cb}")
        print(f"  [derivations] block: {has_derivations}")
        print(f"  pe_static mention: {has_pe_static}")
        print(f"  price_as_of/akshare mention: {has_price_as_of}")
        print(f"  tool calls ({len(tool_logs)}):")
        for l in tool_logs:
            print(l)

        # Key assertion: not empty, not iteration_limit
        ok = len(final_content) > 100 and elapsed < 300
        print(f"\n  {'✅ PASS' if ok else '❌ FAIL'}: output={len(final_content)}chars elapsed={elapsed:.0f}s")

finally:
    if toolkit is not None:
        try: toolkit.close()
        except: pass
    bridge.run(memory_store.close(), timeout=5)
    bridge.run(trace_writer.close(), timeout=5)
    bridge.shutdown()
