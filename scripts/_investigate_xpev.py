"""Quick XPEV investigation: what tools does the agent call, what facts get registered?"""
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
from cagent_os.shared.async_bridge import AsyncBridge
from cagent_os.user_skills import FilesystemUserSkillStore, UserSkillService
from cagent_os.agents import AgentRuntime
from cagent_os.interfaces.cli import build_registry

QUESTION = "小鹏 Q1 2026 营收同比怎么样？"

settings = get_settings()
project_root = Path(__file__).resolve().parent.parent
skill_store = FilesystemUserSkillStore(
    data_dir=(project_root / settings.skills_data_dir).resolve(),
    shared_skills_dir=(project_root / settings.shared_skills_dir).resolve() if settings.shared_skills_dir else None,
)
skill_service = UserSkillService(store=skill_store)
Path("data").mkdir(exist_ok=True)
bridge = AsyncBridge()
memory_store = SqliteMemoryStore(db_path="data/memory.db")
bridge.run(memory_store.open(), timeout=10)
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
snapshot = skill_service.load_snapshot(user_id)
conv = conversation_service.create_conversation(
    principal_id=principal_id, user_id=user_id, user_skill_snapshot=snapshot,
)

print(f"\n{'='*70}\nQUESTION: {QUESTION}\n{'='*70}")
final_content = ""
t0 = time.perf_counter()
try:
    for entry in engine.run(
        conversation_id=conv.conversation_id,
        principal_id=principal_id,
        user_content=QUESTION,
        skip_provenance_gate=True,
    ):
        if entry.type == "message.assistant_added":
            final_content = entry.content or ""
except Exception as exc:
    print(f"RUN FAILED: {exc}")
    import traceback; traceback.print_exc()
    sys.exit(1)

elapsed = time.perf_counter() - t0
print(f"\nElapsed: {elapsed:.1f}s")
print(f"Output length: {len(final_content)} chars")

fact_registry = executor.fact_registry
facts = fact_registry.facts

# Analyze facts
by_kind = {}
by_source = {}
for f in facts:
    by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    by_source[f.source] = by_source.get(f.source, 0) + 1

print(f"\nRegistry: {len(facts)} facts")
print(f"By kind: {json.dumps(by_kind, ensure_ascii=False)}")
print(f"By source: {json.dumps(by_source, ensure_ascii=False)}")
print(f"\nFirst 10 facts:")
for f in facts[:10]:
    val_str = str(f.value)[:80] if f.value else ""
    print(f"  [{f.kind}] source={f.source} capability={f.capability} caliber={f.caliber} value={val_str}")

# Show output snippet
print(f"\nOUTPUT (first 500 chars):")
print(final_content[:500])

if toolkit:
    toolkit.close()
bridge.run(memory_store.close(), timeout=5)
bridge.run(trace_writer.close(), timeout=5)
bridge.shutdown()
