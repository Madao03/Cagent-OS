"""Re-score: run agent WITHOUT gate, capture outputs, then apply V2 checker.

This produces a fair V1-vs-V2 comparison: same checker (V2 strict), 
different agent behaviors (no-gate vs gate).
"""
import json, sys, time
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")

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

QUESTIONS = [
    "小鹏 Q1 2026 营收同比怎么样？",
    "MSTR 的 mNAV 现在是多少？",
    "腾讯 2025 Q3 营收是多少？",
    "BTC 现在处于高估还是低估区间？用数据说话",
    "现在美国的联邦基金利率和 10 年期国债收益率分别是多少？",
]

RESCALES = [100.0, 0.01, 1e4, 1e-4, 1e8, 1e-8]


def classify_untracked(value, registry_facts):
    data_vals = [
        f.value for f in registry_facts
        if isinstance(f.value, (int, float)) and not isinstance(f.value, bool)
        and f.kind in ("data", "text_citation") and f.value != 0
    ]
    for rv in data_vals:
        for s in RESCALES:
            if rv != 0 and abs(value * s - rv) <= abs(rv) * 0.01:
                return "normalization"
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
    return "hallucination"


def main():
    settings = get_settings()
    project_root = Path(__file__).resolve().parent.parent

    skill_store = FilesystemUserSkillStore(
        data_dir=(project_root / settings.skills_data_dir).resolve(),
        shared_skills_dir=(project_root / settings.shared_skills_dir).resolve()
        if settings.shared_skills_dir else None,
    )
    skill_service = UserSkillService(store=skill_store)
    Path("data").mkdir(exist_ok=True)
    bridge = AsyncBridge()
    memory_store = SqliteMemoryStore(db_path="data/memory.db")
    bridge.run(memory_store.open(), timeout=10)
    registry, toolkit = build_registry(
        mcp_manager=None, skill_service=skill_service, memory_api=memory_store,
    )
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
        for i, q in enumerate(QUESTIONS, 1):
            print(f"\n{'='*70}\n[{i}/5] {q}\n{'='*70}")
            snapshot = skill_service.load_snapshot(user_id)
            conv = conversation_service.create_conversation(
                principal_id=principal_id, user_id=user_id, user_skill_snapshot=snapshot,
            )
            t0 = time.perf_counter()
            final_content = ""
            try:
                for entry in engine.run(
                    conversation_id=conv.conversation_id,
                    principal_id=principal_id,
                    user_content=q,
                    skip_provenance_gate=True,
                ):
                    if entry.type == "message.assistant_added":
                        final_content = entry.content or ""
            except Exception as exc:
                print(f"  RUN FAILED: {exc}")
                import traceback; traceback.print_exc()
                results.append({"question": q, "error": str(exc)})
                continue
            elapsed = time.perf_counter() - t0

            fact_registry = executor.fact_registry

            # ★ Score with V2 checker (strict)
            prov = check_provenance(final_content, fact_registry)

            # Classify untraced
            buckets = {"derived": [], "normalization": [], "hallucination": []}
            for u in prov.untraced_numbers:
                b = classify_untracked(u.value, fact_registry.facts)
                buckets[b].append(u.raw)

            tc = sum(1 for t in prov.traced_numbers
                     if t.kind in ("text_citation", "verified_citation"))
            td = prov.traced - tc
            vc = prov.verified_citation

            rec = {
                "question": q,
                "elapsed_s": round(elapsed, 1),
                "output_chars": len(final_content),
                "output_text": final_content,
                "registry_facts": len(fact_registry.facts),
                "traced_data": td,
                "traced_text_citation": tc,
                "verified_citation": vc,
                "derived": buckets["derived"],
                "normalization": buckets["normalization"],
                "hallucination": buckets["hallucination"],
                "non_data": prov.non_data,
                "sign_conflict": [s.raw for s in prov.sign_conflict_numbers],
            }
            results.append(rec)

            print(f"Elapsed: {elapsed:.1f}s")
            print(f"Registry facts: {len(fact_registry.facts)}")
            print(f"Traced: {td} data + {tc} text = {prov.traced} (vc={vc})")
            print(f"Untraced: {prov.untraced}")
            print(f"  derived: {len(buckets['derived'])}")
            print(f"  normalization: {len(buckets['normalization'])}")
            print(f"  hallucination: {len(buckets['hallucination'])}")
            print(f"Non-data: {prov.non_data}")
            print(f"Sign conflicts: {prov.sign_conflicts}")
            print(f"\nOUTPUT (first 300 chars):\n{final_content[:300]}...")

    finally:
        if toolkit is not None:
            try:
                toolkit.close()
            except Exception:
                pass
        bridge.run(memory_store.close(), timeout=5)
        bridge.run(trace_writer.close(), timeout=5)
        bridge.shutdown()

    # Save results
    out_path = Path("scripts/provenance_baseline_v1_rescored.json")
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
