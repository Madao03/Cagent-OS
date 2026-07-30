"""Re-run Tencent Q3 question with provenance gate active."""
import sys, time
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

QUESTION = "腾讯 2025 Q3 营收是多少？"

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
print(f"\n{'='*70}\nOUTPUT:\n{'='*70}")
print(final_content)

# Quick provenance check
from cagent_os.provenance import check_provenance
result = check_provenance(final_content, executor.fact_registry)
print(f"\n{'='*70}\nPROVENANCE:\n{'='*70}")
print(f"Total: {result.total_numbers}, traced: {result.traced}, untraced: {result.untraced}")
print(f"Sign conflicts: {result.sign_conflicts}, verbatim citations: {result.verified_citation}")
if result.traced_numbers:
    print(f"\nTraced numbers:")
    for t in result.traced_numbers:
        extra = ""
        if t.kind == "verified_citation":
            extra = f" [verbatim, source={t.source}]"
            if t.citation_sentence:
                extra += f" sentence={t.citation_sentence[:60]}..."
        else:
            extra = f" [{t.kind or 'data'}, source={t.source}]"
        print(f"  {t.raw} (value={t.value}){extra}")
if result.untraced_numbers:
    print(f"\nUntraced numbers:")
    for u in result.untraced_numbers:
        print(f"  {u.raw} (value={u.value})")
if result.sign_conflict_numbers:
    print(f"\nSign conflicts:")
    for s in result.sign_conflict_numbers:
        print(f"  {s.raw}: {s.conflict_detail[:80]}")

# Cleanup
if toolkit:
    toolkit.close()
bridge.run(memory_store.close(), timeout=5)
bridge.run(trace_writer.close(), timeout=5)
bridge.shutdown()
