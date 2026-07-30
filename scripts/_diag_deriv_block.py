"""Diagnose: agent writes [derivations] block but derived_traced=0 — why?"""
import sys, time, re
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
from cagent_os.provenance import check_provenance, extract_derivations_block, verify_derivations

QUESTION = "小鹏 Q4 2025 营收同比怎么样？"

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

pid = settings.default_principal_id
uid = settings.default_user_id
snap = skill_service.load_snapshot(uid)
conv = conversation_service.create_conversation(principal_id=pid, user_id=uid, user_skill_snapshot=snap)

fc = ""
t0 = time.perf_counter()
for entry in engine.run(
    conversation_id=conv.conversation_id,
    principal_id=pid,
    user_content=QUESTION,
    skip_provenance_gate=True,
):
    if entry.type == "message.assistant_added":
        fc = entry.content or ""

print(f"Output: {len(fc)} chars in {time.perf_counter()-t0:.1f}s")
print(f"Registry: {len(executor.fact_registry.facts)} facts")

# Show the derivation block area
if "[derivations]" in fc:
    idx = fc.index("[derivations]")
    print(f"\n{'='*60}")
    print("DERIVATION BLOCK IN OUTPUT:")
    print(fc[idx:])
    print(f"{'='*60}")

# Parse and verify
cleaned, dr = extract_derivations_block(fc)
print(f"\nextract_derivations_block: found={dr is not None}")
if dr:
    print(f"  Derivations parsed: {len(dr.derivations)}")
    for d in dr.derivations:
        print(f"    line='{d.line}'")
        print(f"    formula='{d.formula}'")
        print(f"    parent_ids={d.parent_ids}")
        print(f"    parent_semantic={d.parent_semantic}")
        print(f"    claimed_result={d.claimed_result}")

    verify_derivations(dr, executor.fact_registry)
    print(f"  Verified: {dr.verified_count}, Errors: {dr.error_count}")
    for err in dr.errors:
        print(f"    ERROR: {err}")
    for vd in dr.verified:
        print(f"    OK: {vd.formula_display} = {vd.computed_value} {vd.result_display_hint}")

# Show fact_refs that the agent would have seen
print(f"\n{'='*60}")
print("REGISTRY FACTS (what agent saw in _fact_refs):")
for f in executor.fact_registry.facts:
    if f.kind == "data":
        cal = f.caliber or ""
        pe = getattr(f, 'period_end', '') or ''
        pt = getattr(f, 'period_type', '') or ''
        print(f"  {f.id}: {cal} value={f.value} period_end={pe} period_type={pt}")

if toolkit:
    toolkit.close()
bridge.run(memory_store.close(), timeout=5)
bridge.run(trace_writer.close(), timeout=5)
bridge.shutdown()
