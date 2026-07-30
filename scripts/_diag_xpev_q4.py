"""Diagnostic: XPEV Q4 2025 with TOOL CALL LOGGING + registry dump.

Distinguishes "agent didn't call tool" from "tool returned but registry failed."
"""
import sys, time, json, logging
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
from cagent_os.provenance import check_provenance

# Enable debug logging to see tool calls
logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')

QUESTION = "小鹏 Q4 2025 营收同比怎么样？"

# ★ Monkey-patch ToolDispatcher.execute to log every tool call
_original_execute = ToolDispatcher.execute

def _logged_execute(self, request):
    print(f"\n[TOOL CALL] {request.capability_id}")
    print(f"  args: {json.dumps(request.arguments, ensure_ascii=False)[:200]}")
    t0 = time.perf_counter()
    result = _original_execute(self, request)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    status = result.status
    content_preview = ""
    if isinstance(result.content, dict):
        rc = result.content.get("record_count", "")
        gc = result.content.get("guidance_count", "")
        err = result.content.get("error", "")
        content_preview = f" record_count={rc} guidance_count={gc} error={err}"[:120]
    print(f"  → {status} ({elapsed_ms:.0f}ms){content_preview}")
    return result

ToolDispatcher.execute = _logged_execute

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
print("TOOL CALLS:")
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

fact_registry = executor.fact_registry
facts = fact_registry.facts

print(f"\n{'='*70}\nRESULTS:")
print(f"Elapsed: {elapsed:.1f}s | Output: {len(final_content)} chars")
print(f"Registry: {len(facts)} facts")

# By kind
by_kind = {}
for f in facts:
    by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
print(f"By kind: {json.dumps(by_kind, ensure_ascii=False)}")

# By source
by_source = {}
for f in facts:
    by_source[f.source] = by_source.get(f.source, 0) + 1
print(f"By source: {json.dumps(by_source, ensure_ascii=False)}")

# Show financial fields from EDGAR
edgar_facts = [f for f in facts if f.source == "EDGAR"]
print(f"\nEDGAR facts: {len(edgar_facts)}")
fin_keys = ["revenue", "net_income", "gross_profit", "operating_income",
            "eps_diluted", "cost_of_sales"]
for k in fin_keys:
    vals = [f for f in edgar_facts if f.caliber == k]
    if vals:
        print(f"  {k}: {len(vals)} fact(s) = {[v.value for v in vals]}")

# Show all EDGAR facts
print(f"\nAll EDGAR calibers:")
for f in edgar_facts:
    print(f"  caliber={f.caliber} value={f.value} currency={f.currency} period_type={f.period_type}")

# Provenance
prov = check_provenance(final_content, fact_registry)
print(f"\nProvenance: {prov.traced} traced + {prov.untraced} untraced (vc={prov.verified_citation})")
print(f"Total numbers: {prov.total_numbers}, non-data: {prov.non_data}")

# Show traced
if prov.traced_numbers:
    print(f"\nTraced ({len(prov.traced_numbers)}):")
    for t in prov.traced_numbers[:20]:
        extra = f" caliber={t.fact_id}"[:40] if t.fact_id else ""
        print(f"  {t.raw} (value={t.value}) source={t.source}{extra}")

# Show untraced  
if prov.untraced_numbers:
    print(f"\nUntraced ({len(prov.untraced_numbers)}):")
    for u in prov.untraced_numbers[:20]:
        print(f"  {u.raw} (value={u.value})")

# Output snippet
print(f"\nOUTPUT (first 400 chars):")
print(final_content[:400])

if toolkit:
    toolkit.close()
bridge.run(memory_store.close(), timeout=5)
bridge.run(trace_writer.close(), timeout=5)
bridge.shutdown()
