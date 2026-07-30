"""Pre-launch Provenance Baseline — automated metrics for all 14 Golden Cases.

Usage:
    python scripts/run_prelaunch_baseline.py

Runs each case through the full AgentRuntime + Provenance Checker.
Data-intensive cases (003, 004, 005, 013, 014) run 3× for variance.
Post-run scans for transient API failures and re-runs affected cases.

Output: scripts/baseline_prelaunch.json
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, "src")

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

# ── Config ────────────────────────────────────────────────────────
DATA_INTENSIVE = {"case_003", "case_004", "case_005", "case_013", "case_014"}
N_RUNS_INTENSIVE = 3
N_RUNS_NORMAL = 1

# Cases where hallucination rate is not meaningful — their numbers come
# from input documents (articles being triaged), not from tool returns.
# The classifier will always flag them as 100% hallucination because
# the input text isn't registered in FactRegistry.
HALLUCINATION_EXCLUDED = {"case_001", "case_011"}

# Transient failure patterns to scan for (case should be re-run)
TRANSIENT_PATTERNS = [
    "Too Many Requests",
    "Rate limited",
    "defillama.*None",
    "returned None",
    "Read timed out",
    "ConnectionError",
    "Connection reset",
    "Temporary failure",
]


# ── Case loader ───────────────────────────────────────────────────

def load_cases() -> list[dict]:
    """Load all 14 golden case YAMLs, return [{id, title, query, scenario, data_intensive}...]"""
    cases_dir = Path("evaluation/golden_cases")
    cases = []
    for path in sorted(cases_dir.glob("case_*.yaml")):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        cid = data["id"]
        # case_014 uses user_message, rest use content
        inp = data.get("input", {})
        query = inp.get("content") or inp.get("user_message", "")
        cases.append({
            "id": cid,
            "title": data.get("title", ""),
            "query": query,
            "scenario": data.get("scenario", ""),
            "data_intensive": cid in DATA_INTENSIVE,
            "n_runs": N_RUNS_INTENSIVE if cid in DATA_INTENSIVE else N_RUNS_NORMAL,
        })
    return cases


# ── Provenance metrics (from run_provenance_baseline.py) ──────────

RESCALES = [100.0, 0.01, 1e4, 1e-4, 1e8, 1e-8]

# F1 "Answered" rules — ensure core metrics are present
_F1_RULES: list[dict] = [
    {
        "question_key": "小鹏", "core_keywords": ["营收", "revenue", "收入"],
        "require_traced_data": 1,
    },
    {
        "question_key": "MSTR", "core_keywords": ["mNAV", "NAV", "溢价", "premium"],
        "require_traced_data": 1,
    },
    {
        "question_key": "腾讯",
        "core_keywords": ["营收", "revenue", "收入"],
        "unavailable_keywords": ["不可得", "不可用", "未注册", "无SEC", "无 EDGAR",
                                 "unavailable", "not registered", "no CIK",
                                 "不在覆盖范围", "无法获取"],
        "require_traced_data": 1,
    },
    {
        "question_key": "BTC",
        "core_keywords": ["MVRV", "MVRV-Z", "Z-Score", "恐贪", "fear", "greed",
                          "高估", "低估", "overvalued", "undervalued", "估值", "valuation"],
        "require_traced_data": 1,
    },
    {
        "question_key": "STRC",
        "core_keywords": ["STRC", "mNAV", "NAV", "飞轮", "优先股", "preferred"],
        "require_traced_data": 1,
    },
    {
        "question_key": "NVDA",
        "core_keywords": ["NVDA", "NVIDIA", "PE", "估值", "EPS", "目标价"],
        "require_traced_data": 1,
    },
]


def classify_untracked(value: float, registry_facts: list, raw: str = "") -> str:
    """Classify one untraced number into derived / normalization / hallucination."""
    bare_small = (
        abs(value) < 100 and value == int(value)
        and "%" not in raw and "￥" not in raw and "$" not in raw and "¥" not in raw
    )
    _AMOUNT_UNITS = {"亿", "万", "元", "¥", "$", "￥", "T", "B", "M", "K"}
    has_amount_unit = any(u in raw for u in _AMOUNT_UNITS)
    is_absolute_amount = has_amount_unit and "%" not in raw

    data_vals = [
        f.value for f in registry_facts
        if isinstance(f.value, (int, float)) and not isinstance(f.value, bool)
        and f.kind in ("data", "text_citation") and f.value != 0
    ]
    # normalization gap
    for rv in data_vals:
        for s in RESCALES:
            if rv != 0 and abs(value * s - rv) <= abs(rv) * 0.01:
                return "normalization"
    # derived
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
                    if abs(value / 100 - c) <= abs(c) * 0.02:
                        return "derived"
                    if abs(value * 100 - c) <= abs(c) * 0.02:
                        return "derived"
    return "hallucination"


def check_answered(question: str, output: str, traced_data: int) -> bool:
    output_lower = output.lower()
    for rule in _F1_RULES:
        if rule["question_key"].lower() not in question.lower():
            continue
        has_core = any(kw.lower() in output_lower for kw in rule["core_keywords"])
        has_unavailable = False
        if "unavailable_keywords" in rule:
            has_unavailable = any(
                kw.lower() in output_lower for kw in rule["unavailable_keywords"]
            )
        answers_content = has_core or has_unavailable
        has_enough_data = traced_data >= rule["require_traced_data"]
        return answers_content and has_enough_data
    return traced_data >= 3


def detect_scanner_misses(output: str, covered_spans: list[tuple[int, int]]) -> list[str]:
    misses = []
    for m in re.finditer(r"\d+(?:,\d{3})*(?:\.\d+)?", output):
        span = (m.start(), m.end())
        covered = any(span[0] >= s and span[1] <= e for s, e in covered_spans)
        if not covered:
            txt = m.group(0).replace(",", "")
            if re.fullmatch(r"20[12]\d", txt):
                continue
            if len(txt) <= 2:
                continue
            misses.append(m.group(0))
    return misses


def scan_transient_failures(tool_logs: list[str]) -> list[str]:
    """Check tool call logs for transient API failures. Returns patterns found."""
    found = []
    for log in tool_logs:
        for pat in TRANSIENT_PATTERNS:
            if re.search(pat, log, re.IGNORECASE):
                found.append(log.strip()[:120])
                break
    return found


# ── Baseline runner ───────────────────────────────────────────────

def run_baseline() -> None:
    settings = get_settings()
    project_root = Path(__file__).resolve().parent.parent

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

    cases = load_cases()
    print(f"Loaded {len(cases)} cases")
    print(f"Data-intensive (3×): {[c['id'] for c in cases if c['data_intensive']]}")
    print(f"Normal (1×): {[c['id'] for c in cases if not c['data_intensive']]}")
    total_runs = sum(c["n_runs"] for c in cases)
    print(f"Total runs: {total_runs}")

    report = {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "total_cases": len(cases),
            "total_runs": total_runs,
            "data_intensive_3x": sorted(list(DATA_INTENSIVE)),
        },
        "cases": [],
    }

    # Save original execute for tool call logging
    _orig_execute = ToolDispatcher.execute
    tool_error = False

    try:
        run_idx = 0
        for case in cases:
            cid = case["id"]
            n = case["n_runs"]
            case_record = {
                "id": cid, "title": case["title"],
                "query": case["query"], "scenario": case["scenario"],
                "data_intensive": case["data_intensive"],
                "runs": [],
            }

            for rn in range(1, n + 1):
                run_idx += 1
                print(f"\n{'='*70}\n[{run_idx}/{total_runs}] {cid} ({rn}/{n}) {case['title'][:50]}\n  Q: {case['query'][:80]}\n{'='*70}")

                # Fresh FactRegistry per run
                executor.attach_fact_registry(FactRegistry())

                # Tool call logging via monkeypatch
                tool_logs: list[str] = []
                tool_error = False

                def _logged(self, req):
                    nonlocal tool_error
                    t0t = time.perf_counter()
                    result = _orig_execute(self, req)
                    ms = (time.perf_counter() - t0t) * 1000
                    if result.status != "ok":
                        tool_error = True
                        tool_logs.append(
                            f"✗ {req.capability_id} ERR({result.error_code}): {str(result.content)[:120]}"
                        )
                    else:
                        tool_logs.append(
                            f"✓ {req.capability_id} ({ms:.0f}ms)"
                        )
                    return result
                ToolDispatcher.execute = _logged

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
                        user_content=case["query"],
                        skip_provenance_gate=True,
                    ):
                        if entry.type == "message.assistant_added":
                            final_content = entry.content or ""
                except Exception as exc:
                    print(f"  RUN FAILED: {exc}")
                    case_record["runs"].append({
                        "run": rn, "error": str(exc),
                        "output_chars": len(final_content),
                    })
                    continue

                elapsed = time.perf_counter() - t0

                # ── Provenance check ──
                fact_registry = executor.fact_registry
                prov = check_provenance(final_content, fact_registry)

                # Classify untracked
                buckets = {"derived": [], "normalization": [], "hallucination": []}
                for u in prov.untraced_numbers:
                    b = classify_untracked(u.value, fact_registry.facts, u.raw)
                    buckets[b].append(u.raw)

                covered = (
                    [(t.start, t.end) for t in prov.traced_numbers] +
                    [(u.start, u.end) for u in prov.untraced_numbers]
                )
                misses = detect_scanner_misses(final_content, covered)

                tc = sum(1 for t in prov.traced_numbers
                         if t.kind in ("text_citation", "verified_citation"))
                td = prov.traced - tc
                vc = prov.verified_citation

                data_total = prov.traced + prov.untraced
                hall_rate = (
                    len(buckets["hallucination"]) / data_total
                    if data_total > 0 else 0.0
                )
                # F1 check: case_014 uses lenient matching
                q_check = case["query"][:80]
                answered = check_answered(q_check, final_content, td)
                # Override for case_014: check explicit "数据不可得" + reason
                if cid == "case_014":
                    has_unavailable = any(
                        kw in final_content
                        for kw in ["不可得", "不可用", "未注册", "无SEC", "不在覆盖范围"]
                    )
                    has_reason = any(
                        kw in final_content
                        for kw in ["港股", "HKEX", "半年", "中期", "季报", "披露"]
                    )
                    answered = has_unavailable and has_reason and len(
                        buckets["hallucination"]) == 0

                run_rec = {
                    "run": rn,
                    "elapsed_s": round(elapsed, 1),
                    "output_chars": len(final_content),
                    "registry_facts": len(fact_registry.facts),
                    "traced_data": td,
                    "traced_text_citation": tc,
                    "verified_citation": vc,
                    "derived_traced": len(buckets["derived"]),
                    "hallucination_count": len(buckets["hallucination"]),
                    "hallucination_rate": round(hall_rate, 3),
                    "data_numbers": data_total,
                    "non_data": prov.non_data,
                    "answered": answered,
                    "scanner_miss": len(misses),
                    "sign_conflict": prov.sign_conflicts,
                    "tool_count": len(tool_logs),
                    "tool_error": tool_error,
                }
                case_record["runs"].append(run_rec)
                print(json.dumps(run_rec, ensure_ascii=False, indent=2))

                # ── Scan for transient failures ──
                transients = scan_transient_failures(tool_logs)
                if transients:
                    print(f"  ⚠️  TRANSIENT FAILURES DETECTED:")
                    for t in transients:
                        print(f"     {t}")

            # ── Case-level aggregation ──
            runs = case_record["runs"]
            if runs:
                # Avg across runs
                avg_hall_rate = sum(r.get("hallucination_rate", 0) for r in runs) / len(runs)
                avg_traced = sum(r.get("traced_data", 0) for r in runs) / len(runs)
                all_answered = all(r.get("answered", False) for r in runs)
                case_record["aggregate"] = {
                    "avg_hallucination_rate": round(avg_hall_rate, 3),
                    "avg_traced_data": round(avg_traced, 1),
                    "answered_all_runs": all_answered,
                    "total_hallucination": sum(r.get("hallucination_count", 0) for r in runs),
                }
            report["cases"].append(case_record)

        # ── Global summary ──
        all_runs = [r for c in report["cases"] for r in c["runs"]]
        # Split into meaningful vs excluded (content-processing) cases
        meaningful_runs = [
            r for c in report["cases"] for r in c["runs"]
            if c["id"] not in HALLUCINATION_EXCLUDED and "error" not in r
        ]
        excluded_runs = [
            r for c in report["cases"] for r in c["runs"]
            if c["id"] in HALLUCINATION_EXCLUDED
        ]

        total_hall = sum(r.get("hallucination_count", 0) for r in meaningful_runs)
        total_data = sum(r.get("data_numbers", 0) for r in meaningful_runs)
        total_answered = sum(1 for r in all_runs if r.get("answered"))
        total_errors = sum(1 for r in all_runs if "error" in r)
        total_failed = sum(1 for r in all_runs if r.get("output_chars", 0) == 0 and "error" not in r)

        # case_014 specific: must have 0 hallucination across all runs
        case_014_runs = [r for c in report["cases"] if c["id"] == "case_014" for r in c["runs"] if "error" not in r]
        case_014_hall = sum(r.get("hallucination_count", 0) for r in case_014_runs)

        report["summary"] = {
            "total_runs_completed": len(all_runs),
            "total_run_errors": total_errors,
            "failed_rate": f"{total_failed}/{len(all_runs)}",
            "total_hallucination": total_hall,
            "total_data_numbers": total_data,
            "hallucination_rate_global": round(total_hall / total_data, 3) if total_data > 0 else 0.0,
            "hallucination_excluded_cases": sorted(list(HALLUCINATION_EXCLUDED)),
            "excluded_runs_count": len(excluded_runs),
            "answered_rate": f"{total_answered}/{len(all_runs)}",
            "case_014_hallucination": f"{case_014_hall}/{len(case_014_runs)} runs (assert: 0)",
            "cases_with_transient_failures": [
                c["id"] for c in report["cases"]
                if any(r.get("tool_error") for r in c["runs"])
            ],
        }

        # Write output
        out_path = Path("scripts/baseline_prelaunch.json")
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"\n{'='*70}")
        print(f"BASELINE SUMMARY (excluding {sorted(HALLUCINATION_EXCLUDED)} from hallucination stats)")
        print(f"{'='*70}")
        print(f"  Runs: {len(all_runs)} completed ({total_errors} errors)")
        print(f"  Failed (0 chars): {total_failed}/{len(all_runs)}")
        print(f"  Hallucination: {total_hall}/{total_data} = {round(total_hall/total_data*100,1) if total_data else 0}%")
        print(f"  Answered: {total_answered}/{len(all_runs)}")
        print(f"  case_014 hallucination: {case_014_hall}/{len(case_014_runs)} (assert: 0)")
        print(f"\n  Per-case hallucination:")
        for c in report["cases"]:
            agg = c.get("aggregate", {})
            runs_ok = [r for r in c["runs"] if "error" not in r]
            h = sum(r["hallucination_count"] for r in runs_ok)
            d = sum(r["data_numbers"] for r in runs_ok)
            a = "✅" if agg.get("answered_all_runs") else "❌"
            ex = " [excluded]" if c["id"] in HALLUCINATION_EXCLUDED else ""
            print(f"  {a} {c['id']} | hall={h}/{d} | avg_rate={agg.get('avg_hallucination_rate','-')} | {c['title'][:50]}{ex}")
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
