"""Diagnose 13.90 tracing failure — step through checker passes.

Runs a real XPEV Q4 agent call, captures the registry, then traces
"净收入 -13.9 亿（亏损）" through each checker pass to identify
which branch it falls into and why.
"""
import sys, time, json, re
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
from cagent_os.provenance.checker import (
    check_provenance, _extract_preceding_clause,
    _check_verbatim_citation, _make_search_variants,
)
from cagent_os.provenance.normalizer import extract_numbers

QUESTION = "小鹏 Q4 2025 营收同比怎么样？"

# Set up runtime
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
    sys.exit(1)

fact_registry = executor.fact_registry
print(f"\n{'='*70}")
print(f"Registry: {len(fact_registry.facts)} facts")
print(f"Output: {len(final_content)} chars")

# ── Show all net_income values in registry ──
print(f"\n{'='*70}")
print("NET INCOME VALUES IN REGISTRY:")
for f in fact_registry.facts:
    try:
        fv = float(f.value)
    except (ValueError, TypeError):
        continue
    if hasattr(f, 'caliber') and 'net_income' in str(f.caliber).lower():
        print(f"  id={f.id} value={f.value} period_end={f.period_end} period_type={f.period_type} precision={f.precision}")

# Also show any fact with value in the range of 13.9亿
print(f"\n{'='*70}")
print("ALL FACTS WITH VALUE NEAR ±1.39e9:")
for f in fact_registry.facts:
    try:
        fv = float(f.value)
    except (ValueError, TypeError):
        continue
    if 1.3e9 <= abs(fv) <= 1.5e9:
        print(f"  id={f.id} value={fv} caliber={getattr(f, 'caliber', 'N/A')} source={f.source} period_end={f.period_end}")

# ── Find "净收入 -13.9 亿（亏损）" in output ──
print(f"\n{'='*70}")
print("SEARCHING FOR '净收入' PHRASES IN OUTPUT:")
for m in re.finditer(r'净[收入利润亏损].{0,30}', final_content):
    ctx_start = max(0, m.start()-10)
    ctx_end = min(len(final_content), m.end()+30)
    print(f"  [{m.start()}:{m.end()}] ...{final_content[ctx_start:ctx_end]}...")

# ── Extract numbers and step through checker ──
print(f"\n{'='*70}")
print("STEPPING THROUGH CHECKER FOR 13.9亿:")

numbers = extract_numbers(final_content)
LOSS_KEYWORDS = {"亏损", "损失", "下降", "减少", "负", "净亏",
                 "loss", "decrease", "decline", "negative", "drop"}
GAIN_KEYWORDS = {"利润", "盈利", "增长", "增加", "正", "净利",
                 "profit", "gain", "increase", "growth", "positive"}

for num in numbers:
    # Look for 13.9亿 range
    if not (1.3e9 <= abs(num.value) <= 1.5e9):
        continue

    print(f"\n  Number: raw='{num.raw}' value={num.value} pos=[{num.start}:{num.end}]")
    context_window = _extract_preceding_clause(final_content, num.start)
    print(f"  Context window: '{context_window}'")
    print(f"  Has loss keyword: {any(kw in context_window for kw in LOSS_KEYWORDS)}")
    print(f"  Has gain keyword: {any(kw in context_window for kw in GAIN_KEYWORDS)}")

    # Pass 1: normal match
    match1 = fact_registry.find_by_value(num.value, tolerance=0.005, sign_context=context_window)
    print(f"  Pass 1 (normal): match={'YES' if match1 else 'NO'}")
    if match1:
        print(f"    → fact_id={match1.id} value={match1.value} caliber={getattr(match1, 'caliber', 'N/A')}")
    else:
        # Why no match? Check each registry fact
        print(f"  → Checking registry facts manually:")
        for f in fact_registry.facts:
            try:
                fv = float(f.value)
            except (ValueError, TypeError):
                continue
            if f.kind in ("news", "verified_citation"):
                continue
            # Exact match check
            if abs(fv - num.value) <= abs(fv) * 0.005:
                print(f"    EXACT MATCH: id={f.id} value={fv} caliber={getattr(f, 'caliber', 'N/A')}")
            # Abs match check
            implies_neg = any(kw in context_window or kw in context_window.lower() for kw in LOSS_KEYWORDS)
            if (fv < 0 and num.value > 0 and implies_neg) or (fv > 0 and num.value < 0 and any(kw in context_window or kw in context_window.lower() for kw in GAIN_KEYWORDS)):
                if abs(abs(fv) - abs(num.value)) <= abs(fv) * 0.005:
                    print(f"    ABS MATCH: id={f.id} value={fv} caliber={getattr(f, 'caliber', 'N/A')}")
            # Any value within the same magnitude
            if 1e8 <= abs(fv) <= 1e11:
                print(f"    NEARBY: id={f.id} value={fv} caliber={getattr(f, 'caliber', 'N/A')} diff={abs(fv - num.value):.1e} period_end={f.period_end}")

    # Pass 2: force_abs
    match2 = fact_registry.find_by_value(num.value, tolerance=0.005, force_abs=True)
    print(f"  Pass 2 (force_abs): match={'YES' if match2 else 'NO'}")
    if match2:
        print(f"    → fact_id={match2.id} value={match2.value}")

    # Pass 3: verbatim
    cit = _check_verbatim_citation(num, fact_registry)
    print(f"  Pass 3 (verbatim): match={'YES' if cit else 'NO'}")

# ── Also test with the specific text in isolation ──
print(f"\n{'='*70}")
print("ISOLATION TEST: check_provenance('净收入 -13.9 亿（亏损）', registry)")

test_texts = [
    "净收入 -13.9 亿（亏损）",
    "净亏损 13.90 亿",
    "净亏损 13.9 亿元",
    "-13.9亿",
]
for t in test_texts:
    prov = check_provenance(t, fact_registry)
    traced_count = prov.traced
    status = "TRACED" if traced_count > 0 else "UNTRACED"
    detail = ""
    if prov.traced_numbers:
        tn = prov.traced_numbers[0]
        detail = f"→ fact={tn.fact_id}"
    elif prov.sign_conflict_numbers:
        sc = prov.sign_conflict_numbers[0]
        detail = f"→ sign_conflict: {sc.conflict_detail}"
    print(f"  '{t}': {status} {detail}")
    for u in prov.untraced_numbers:
        print(f"    untraced: raw='{u.raw}' value={u.value}")

if toolkit:
    toolkit.close()
bridge.run(memory_store.close(), timeout=5)
bridge.run(trace_writer.close(), timeout=5)
bridge.shutdown()
