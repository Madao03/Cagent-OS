"""XPEV Q4 2025 baseline × 3 runs — first clean provenance numbers.

Runs with gate skipped (raw output), then scores with current checker.
Tests: 3 runs to get variance, 4-bucket classification, hallucination rate.
"""
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
from cagent_os.provenance import check_provenance

QUESTION = "小鹏 Q4 2025 营收同比怎么样？"
N_RUNS = 3

RESCALES = [100.0, 0.01, 1e4, 1e-4, 1e8, 1e-8]

def classify_untracked(value, registry_facts, raw=""):
    # ══ Bare small integers: |value| < 100 and not a percentage
    # (raw doesn't contain '%' or currency). These are structural (dates,
    # indices) that slipped past the normalizer. Do NOT run derived matching
    # — pairwise search with 25-48 facts will almost certainly find a
    # coincidental match for any small integer.
    bare_small = (
        abs(value) < 100
        and value == int(value)
        and "%" not in raw
        and "￥" not in raw and "$" not in raw and "¥" not in raw
    )
    # ══ Absolute amounts: raw text contains amount units (亿/万/元/$/B/M/K)
    # but NOT "%". These are monetary values or quantities — they cannot be
    # "derived" from registry facts (a quarter's revenue amount can't be
    # computed from two other numbers). If not directly traced, they are
    # hallucination, not derived.
    _AMOUNT_UNITS = {"亿", "万", "元", "¥", "$", "￥", "T", "B", "M", "K"}
    has_amount_unit = any(u in raw for u in _AMOUNT_UNITS)
    is_absolute_amount = has_amount_unit and "%" not in raw
    data_vals = [
        f.value for f in registry_facts
        if isinstance(f.value, (int, float)) and not isinstance(f.value, bool)
        and f.kind in ("data", "text_citation") and f.value != 0
    ]
    for rv in data_vals:
        for s in RESCALES:
            if rv != 0 and abs(value * s - rv) <= abs(rv) * 0.01:
                return "normalization"
    if not bare_small and not is_absolute_amount:
        for a in data_vals:
            for b in data_vals:
                if a == b or b == 0:
                    continue
                candidates = [a / b, a - b, (a - b) / abs(b), a + b]
                for c in candidates:
                    if c == 0:
                        continue
                    if abs(value - c) <= abs(c) * 0.02:
                        return "derived"
                    # Percentage bridge: "38.2%" vs ratio 0.382
                    if abs(value / 100 - c) <= abs(c) * 0.02:
                        return "derived"
                    if abs(value * 100 - c) <= abs(c) * 0.02:
                        return "derived"
    # ⚠️ Derived classification via pairwise reverse-search is an approximation.
    # False positive rate rises with registry size (25-48 facts → hundreds of pairs).
    # P1 fix: derived chain (§3) — agent explicitly declares derivation parents.
    return "hallucination"

def run_once():
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
    tool_calls_log = []
    _orig_execute = ToolDispatcher.execute
    def _logged(self, req):
        t0t = time.perf_counter()
        result = _orig_execute(self, req)
        ms = (time.perf_counter() - t0t) * 1000
        tool_calls_log.append({
            "capability": req.capability_id,
            "args": dict(req.arguments) if req.arguments else {},
            "status": result.status,
            "elapsed_ms": round(ms),
        })
        return result
    ToolDispatcher.execute = _logged

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
        return {"error": str(exc)}
    finally:
        ToolDispatcher.execute = _orig_execute

    elapsed = time.perf_counter() - t0
    fact_registry = executor.fact_registry
    prov = check_provenance(final_content, fact_registry)

    # Classify
    buckets = {"derived": [], "normalization": [], "hallucination": []}
    for u in prov.untraced_numbers:
        b = classify_untracked(u.value, fact_registry.facts, u.raw)
        buckets[b].append(u.raw)

    tc = sum(1 for t in prov.traced_numbers if t.kind in ("text_citation", "verified_citation"))
    td = prov.traced - tc
    data_total = prov.traced + prov.untraced
    hall_rate = len(buckets["hallucination"]) / data_total if data_total > 0 else 0.0

    # ★ P1: derived chain — count traced derivations
    dt = prov.derived_traced
    has_deriv_block = "[derivations]" in final_content
    deriv_lines = 0
    deriv_errors = 0
    if prov.derivation_result:
        deriv_lines = len(prov.derivation_result.derivations)
        deriv_errors = len(prov.derivation_result.errors)

    # ★ F1: Did the output actually answer the question?
    # A low hallucination rate is meaningless if the agent evaded by
    # producing only narrative/ratios without the core metric numbers.
    # For XPEV Q4 2025: output must contain at least one of the key
    # revenue numbers (222.54亿 Q4 2025, 161.05亿 Q4 2024).
    answered = (
        td >= 1  # at least one traced data number
        and ("222.54" in final_content or "161.05" in final_content)
    )

    # ★ Core metric coverage: how many of the must-report metrics
    # appear in the output? Prevents agent from gaming hallucination
    # rate by producing thin answers (3 data numbers ≠ good answer).
    # For XPEV Q4: revenue, YoY growth, gross margin.
    _L = final_content.lower()
    core_metrics = 0
    if "营收" in final_content or "revenue" in _L:
        core_metrics += 1  # revenue mentioned
    if "同比" in final_content or "yoy" in _L or "增长" in final_content:
        core_metrics += 1  # YoY mentioned
    if "毛利" in final_content or "gross" in _L or "margin" in _L:
        core_metrics += 1  # gross margin mentioned
    # Bonus: net profit (扭亏 context)
    if "净利" in final_content or "net_income" in _L or "net profit" in _L:
        core_metrics += 1
    core_coverage = core_metrics  # out of 4 possible

    if toolkit:
        toolkit.close()
    bridge.run(memory_store.close(), timeout=5)
    bridge.run(trace_writer.close(), timeout=5)
    bridge.shutdown()

    return {
        "elapsed_s": round(elapsed, 1),
        "output_chars": len(final_content),
        "registry_facts": len(fact_registry.facts),
        "traced_data": td,
        "traced_text": tc,
        "derived": len(buckets["derived"]),
        "derived_traced": dt,
        "has_deriv_block": has_deriv_block,
        "deriv_lines": deriv_lines,
        "deriv_errors": deriv_errors,
        "normalization": len(buckets["normalization"]),
        "hallucination": len(buckets["hallucination"]),
        "hallucination_rate": round(hall_rate, 3),
        "data_numbers": data_total,
        "non_data": prov.non_data,
        "answered": answered,
        "core_coverage": core_coverage,
        "tool_calls": tool_calls_log,
        "hallucination_items": buckets["hallucination"],
        "derived_items": buckets["derived"],
    }

# Run 3 times
results = []
for run in range(1, N_RUNS + 1):
    print(f"\n{'='*60}\nRun {run}/{N_RUNS}\n{'='*60}")
    r = run_once()
    if "error" in r:
        print(f"  ERROR: {r['error']}")
        continue
    results.append(r)
    status = "✅ ANSWERED" if r.get("answered") else "❌ NOT ANSWERED"
    coverage = r.get("core_coverage", 0)
    cov_str = f" | coverage: {coverage}/4" if coverage else ""
    der_block = " 📦" if r.get("has_deriv_block") else ""
    der_detail = f" ({r.get('deriv_lines',0)} lines, {r.get('deriv_errors',0)} errs)" if r.get("has_deriv_block") else ""
    print(f"  Elapsed: {r['elapsed_s']}s | Output: {r['output_chars']} chars | Registry: {r['registry_facts']} facts")
    print(f"  Traced: {r['traced_data']} data + {r['traced_text']} text | Derived: {r.get('derived_traced', 0)} traced{der_block}{der_detail} | {status}{cov_str}")
    print(f"  Data numbers: {r['data_numbers']} | Non-data: {r['non_data']}")
    print(f"  Post-hoc derived: {r['derived']} | Hallucination: {r['hallucination']} ({r['hallucination_rate']:.0%})")
    print(f"  Tools: {[t['capability'] for t in r['tool_calls']]}")
    if r['hallucination_items']:
        print(f"  Hallucination items: {r['hallucination_items'][:10]}")
    if r['derived_items']:
        print(f"  Derived items: {r['derived_items'][:10]}")

# Summary
print(f"\n{'='*60}\nSUMMARY (n={len(results)})\n{'='*60}")
for key in ["hallucination", "hallucination_rate", "derived_traced", "derived", "traced_data", "traced_text", "data_numbers", "non_data"]:
    vals = [r.get(key, 0) for r in results]
    avg = sum(vals) / len(vals) if vals else 0
    rng = f"{min(vals)}-{max(vals)}" if len(vals) > 1 else str(vals[0]) if vals else "N/A"
    print(f"  {key}: avg={avg:.1f} range=[{rng}]")
blocks = sum(1 for r in results if r.get("has_deriv_block"))
print(f"  has_deriv_block: {blocks}/{len(results)}")
answered_count = sum(1 for r in results if r.get("answered"))
core_cov_vals = [r.get("core_coverage", 0) for r in results]
print(f"  answered: {answered_count}/{len(results)}")
print(f"  core_coverage: avg={sum(core_cov_vals)/len(core_cov_vals):.1f} range=[{min(core_cov_vals)}-{max(core_cov_vals)}]")
