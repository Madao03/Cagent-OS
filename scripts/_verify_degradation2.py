"""Verify the three cases — writes result to JSON for reliable parsing."""
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

results = []
try:
    for cid, query in CASES:
        executor.attach_fact_registry(FactRegistry())
        snapshot = skill_service.load_snapshot(user_id)
        conv = conversation_service.create_conversation(
            principal_id=principal_id, user_id=user_id,
            user_skill_snapshot=snapshot,
        )
        t0 = time.perf_counter()
        final_content = ""
        tool_call_count = 0
        tool_errors = 0
        try:
            for entry in engine.run(
                conversation_id=conv.conversation_id,
                principal_id=principal_id,
                user_content=query,
                skip_provenance_gate=True,
            ):
                if entry.type == "message.assistant_added":
                    final_content = entry.content or ""
                if "tool" in entry.type:
                    tool_call_count += 1
                    if "failed" in entry.type or "error" in str(entry.data).lower():
                        tool_errors += 1
        except Exception as exc:
            results.append({"case": cid, "error": str(exc), "output_chars": len(final_content)})
            continue
        elapsed = time.perf_counter() - t0
        results.append({
            "case": cid,
            "elapsed_s": round(elapsed, 1),
            "output_chars": len(final_content),
            "tool_calls": tool_call_count,
            "tool_errors": tool_errors,
            "has_derivations": "[derivations]" in final_content,
            "has_akshare_mention": "akshare" in final_content.lower(),
            "has_price_note": "close" in final_content.lower() or "price" in final_content.lower(),
            "pass": len(final_content) > 100 and elapsed < 300,
        })
finally:
    if toolkit is not None:
        try: toolkit.close()
        except: pass
    bridge.run(memory_store.close(), timeout=5)
    bridge.run(trace_writer.close(), timeout=5)
    bridge.shutdown()

out = Path("scripts/_verify_result.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
for r in results:
    status = "PASS" if r.get("pass") else "FAIL"
    print(f"{r['case']}: {status} | output={r.get('output_chars',0)} elapsed={r.get('elapsed_s',0)}s derivations={r.get('has_derivations')} akshare={r.get('has_akshare_mention')}")
