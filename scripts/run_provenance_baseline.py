"""Run real-agent provenance baseline — 5 questions, 5-bucket classification.

Runs each question through the full AgentRuntime (same wiring as CLI),
captures the final output + FactRegistry, then classifies every number:

  bucket 1: derived          — ≈ f(a, b) of registry values (ratio/diff/yoy)
  bucket 2: text_citation    — traced via kind=text_citation fact
  bucket 3: normalization    — matches registry with ×100 / ×1e4 / ×1e8 rescale
  bucket 4: scanner_miss     — digit-sequence in output not covered by extractor
  bucket 5: hallucination    — none of the above (Registry has nothing)

Output: scripts/provenance_baseline_report.json + stdout summary.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from cagent_os.config import get_settings
from cagent_os.conversations import ConversationService, InMemoryConversationRepository
from cagent_os.llm.factory import create_backend
from cagent_os.memory.sqlite_store import SqliteMemoryStore
from cagent_os.observability.tracing import TraceWriter
from cagent_os.plugins.executor import ToolDispatcher
from cagent_os.provenance import check_provenance
from cagent_os.shared.async_bridge import AsyncBridge
from cagent_os.user_skills import FilesystemUserSkillStore, UserSkillService
from cagent_os.agents import AgentRuntime
from cagent_os.interfaces.cli import build_registry

QUESTIONS = [
    "小鹏 Q1 2026 营收同比怎么样？",
    "MSTR 的 mNAV 现在是多少？",
    "腾讯 2025 Q3 营收是多少？",
    "BTC 现在处于高估还是低估区间？用数据说话",
    "现在美国的联邦基金利率和 10 年期国债收益率分别是多少？",
]

# ── F1 "Answered" assertion ────────────────────────────────────
# Hallucination rate is meaningless if the agent evades by producing
# only narrative without core metric numbers. F1 prevents "少说话刷分":
# the output must contain at least 1 traced data number AND mention
# the core metric that the question asks about.
#
# For each question, define the minimum keywords that indicate the
# question was actually addressed (not evaded).

_F1_RULES: list[dict] = [
    {
        # XPEV Q1 2026 revenue YoY — must mention revenue numbers
        "question_key": "小鹏",
        "core_keywords": ["营收", "revenue", "收入"],
        "require_traced_data": 1,
    },
    {
        # MSTR mNAV — must mention mNAV/premium
        "question_key": "MSTR",
        "core_keywords": ["mNAV", "NAV", "溢价", "premium"],
        "require_traced_data": 1,
    },
    {
        # Tencent Q3 2025 revenue — out of SEC coverage
        # Correct answer: declare unavailable. Mark answered if output
        # either contains revenue numbers OR explicitly says unavailable.
        "question_key": "腾讯",
        "core_keywords": ["营收", "revenue", "收入"],
        "unavailable_keywords": ["不可得", "不可用", "未注册", "无SEC", "无 EDGAR",
                                 "unavailable", "not registered", "no CIK",
                                 "不在覆盖范围", "无法获取"],
        "require_traced_data": 1,
    },
    {
        # BTC valuation — must mention valuation metrics
        "question_key": "BTC",
        "core_keywords": ["MVRV", "MVRV-Z", "Z-Score", "恐贪", "fear", "greed",
                          "高估", "低估", "overvalued", "undervalued",
                          "估值", "valuation"],
        "require_traced_data": 1,
    },
    {
        # Fed rates — must mention BOTH federal funds rate AND 10Y yield
        "question_key": "联邦基金",
        "core_keywords": ["联邦基金", "federal funds", "国债", "treasury",
                          "收益率", "yield", "利率", "rate"],
        "require_traced_data": 2,  # need at least 2 numbers (both rates)
    },
]


def check_answered(question: str, output: str, traced_data: int) -> bool:
    """F1: Did the output actually answer the question?

    Returns True only if:
    1. traced_data >= rule's require_traced_data threshold
    2. Output mentions at least one core keyword for this question
    3. (For out-of-coverage questions) OR output declares unavailability
    """
    output_lower = output.lower()

    for rule in _F1_RULES:
        if rule["question_key"] not in question:
            continue

        # Check core keywords
        has_core = any(kw.lower() in output_lower for kw in rule["core_keywords"])

        # Check unavailability declaration (for out-of-coverage questions)
        has_unavailable = False
        if "unavailable_keywords" in rule:
            has_unavailable = any(
                kw.lower() in output_lower for kw in rule["unavailable_keywords"]
            )

        # Answered if: (has core keywords OR declares unavailable)
        # AND has enough traced data numbers
        answers_content = has_core or has_unavailable
        has_enough_data = traced_data >= rule["require_traced_data"]

        return answers_content and has_enough_data

    # Fallback: question not matched — require at least 3 data numbers
    return traced_data >= 3

# Chinese unit re-scales to test normalization-gap candidates
RESCALES = [100.0, 0.01, 1e4, 1e-4, 1e8, 1e-8]


def classify_untracked(value: float, registry_facts: list, raw: str = "") -> str:
    """Classify one untraced number into derived / normalization / hallucination."""
    # ══ Bare small integers: |value| < 100 and not a percentage.
    # Pairwise reverse-search with 25-48 facts will almost certainly find
    # a coincidental match (date digits, indices, etc.). Skip derived.
    bare_small = (
        abs(value) < 100
        and value == int(value)
        and "%" not in raw
        and "￥" not in raw and "$" not in raw and "¥" not in raw
    )
    # ══ Absolute amounts: monetary values with units cannot be "derived"
    # from registry facts. Only ratios/percentages are legitimate derivations.
    _AMOUNT_UNITS = {"亿", "万", "元", "¥", "$", "￥", "T", "B", "M", "K"}
    has_amount_unit = any(u in raw for u in _AMOUNT_UNITS)
    is_absolute_amount = has_amount_unit and "%" not in raw
    data_vals = [
        f.value for f in registry_facts
        if isinstance(f.value, (int, float)) and not isinstance(f.value, bool)
        and f.kind in ("data", "text_citation") and f.value != 0
    ]
    # normalization gap: value * scale matches a registry value within 1%
    for rv in data_vals:
        for s in RESCALES:
            if rv != 0 and abs(value * s - rv) <= abs(rv) * 0.01:
                return "normalization"
    # derived: value ≈ a/b, a-b, (a-b)/b for registry pairs (tolerance 2%)
    # Also try value/100 and value*100 — percentages (e.g. -76.4%) vs
    # raw ratios (e.g. -0.764) differ by ×100 but represent the same fact.
    #
    # ⚠️ KNOWN WEAKNESS: pairwise reverse-search is an approximation.
    # With 25-48 registry facts, pairwise combinations number in the hundreds,
    # and a genuine hallucination has non-trivial probability of matching
    # some meaningless combination. False positive rate rises with registry size.
    # P1 fix: derived chain (§3 of PROVENANCE_SYSTEM.md) — agent explicitly
    # declares derivation parents, checker verifies parent facts exist.
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
                    # Percentage bridge: "38.2%" (38.2) vs ratio 0.382
                    if abs(value / 100 - c) <= abs(c) * 0.02:
                        return "derived"
                    # Reverse: ratio 0.382 vs "38.2%" (38.2)
                    if abs(value * 100 - c) <= abs(c) * 0.02:
                        return "derived"
    return "hallucination"


def detect_scanner_misses(output: str, covered_spans: list[tuple[int, int]]) -> list[str]:
    """Find digit-sequences in output NOT covered by the extractor's spans."""
    misses = []
    for m in re.finditer(r"\d+(?:,\d{3})*(?:\.\d+)?", output):
        span = (m.start(), m.end())
        covered = any(span[0] >= s and span[1] <= e for s, e in covered_spans)
        if not covered:
            # ignore years and list indices
            txt = m.group(0).replace(",", "")
            if re.fullmatch(r"20[12]\d", txt):
                continue
            if len(txt) <= 2:
                continue
            misses.append(m.group(0))
    return misses


def run_baseline() -> None:
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

    registry, toolkit = build_registry(mcp_manager=None, skill_service=skill_service, memory_api=memory_store)
    executor = ToolDispatcher(registry=registry)
    repo = InMemoryConversationRepository()
    conversation_service = ConversationService(repository=repo)
    llm_backend = create_backend(settings)
    trace_writer = TraceWriter(db_path="data/trace.db")
    bridge.run(trace_writer.open(), timeout=10)

    engine = AgentRuntime(
        conversation_service=conversation_service,
        event_store=repo,
        llm_backend=llm_backend,
        capability_executor=executor,
        settings=settings,
        memory_api=memory_store,
        trace_writer=trace_writer,
        async_bridge=bridge,
    )

    principal_id = settings.default_principal_id
    user_id = settings.default_user_id

    report = {"questions": [], "totals": {}}
    bucket_totals = {"traced_data": 0, "traced_text_citation": 0, "derived": 0,
                     "normalization": 0, "scanner_miss": 0, "hallucination": 0,
                     "sign_conflict": 0, "non_data": 0}

    try:
        for i, q in enumerate(QUESTIONS, 1):
            print(f"\n{'='*70}\n[{i}/{len(QUESTIONS)}] {q}\n{'='*70}")
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
                ):
                    if entry.type == "message.assistant_added":
                        final_content = entry.content or ""
            except Exception as exc:
                print(f"  RUN FAILED: {exc}")
                report["questions"].append({"question": q, "error": str(exc)})
                continue
            elapsed = time.perf_counter() - t0

            fact_registry = executor.fact_registry
            prov = check_provenance(final_content, fact_registry)

            # classify
            buckets = {"derived": [], "normalization": [], "hallucination": []}
            for u in prov.untraced_numbers:
                b = classify_untracked(u.value, fact_registry.facts, u.raw)
                buckets[b].append(u.raw)

            covered = [(t.start, t.end) for t in prov.traced_numbers] + \
                      [(u.start, u.end) for u in prov.untraced_numbers]
            misses = detect_scanner_misses(final_content, covered)

            tc = sum(1 for t in prov.traced_numbers
                     if t.kind in ("text_citation", "verified_citation"))
            td = prov.traced - tc
            vc = prov.verified_citation

            bucket_totals["traced_data"] += td
            bucket_totals["traced_text_citation"] += tc
            bucket_totals["verified_citation"] = bucket_totals.get("verified_citation", 0) + vc
            bucket_totals["derived"] += len(buckets["derived"])
            bucket_totals["normalization"] += len(buckets["normalization"])
            bucket_totals["hallucination"] += len(buckets["hallucination"])
            bucket_totals["scanner_miss"] += len(misses)
            bucket_totals["sign_conflict"] += prov.sign_conflicts
            bucket_totals["non_data"] += prov.non_data

            # ★ Rate-based metrics: hallucination rate prevents "靠沉默过关"
            # (agent learns to say less to pass the gate).
            data_total = prov.traced + prov.untraced  # data numbers only
            hall_rate = len(buckets["hallucination"]) / data_total if data_total > 0 else 0.0

            # ★ F1 "Answered" assertion — the foundation of the hallucination
            # metric. Without this, the agent can cheat by producing narrative
            # with fewer numbers (temperature sampling naturally does this).
            # answered = traced_data >= threshold AND output mentions core metric.
            answered = check_answered(q, final_content, td)

            qrec = {
                "question": q,
                "elapsed_s": round(elapsed, 1),
                "output_chars": len(final_content),
                "registry_facts": len(fact_registry.facts),
                "traced_data": td,
                "traced_text_citation": tc,
                "verified_citation": vc,
                "derived": buckets["derived"],
                "normalization": buckets["normalization"],
                "hallucination": buckets["hallucination"],
                "hallucination_rate": round(hall_rate, 3),
                "data_numbers": data_total,
                "answered": answered,
                "scanner_miss": misses,
                "sign_conflict": [s.raw for s in prov.sign_conflict_numbers],
                "non_data": prov.non_data,
            }
            report["questions"].append(qrec)
            print(json.dumps(qrec, ensure_ascii=False, indent=2))

        report["totals"] = bucket_totals
        out_path = Path("scripts/provenance_baseline_report.json")
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n{'='*70}\nBASELINE TOTALS\n{'='*70}")
        print(json.dumps(bucket_totals, ensure_ascii=False, indent=2))
        print(f"\nReport written to {out_path}")
    finally:
        if toolkit is not None:
            try:
                toolkit.close()
            except Exception:
                pass
        bridge.run(memory_store.close(), timeout=5)
        bridge.run(trace_writer.close(), timeout=5)
        bridge.shutdown()


if __name__ == "__main__":
    run_baseline()
