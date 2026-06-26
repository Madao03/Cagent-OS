"""Golden Case evaluation runner — Phase 3e.

Usage:
    python evaluation/run_eval.py                    # evaluate all cases
    python evaluation/run_eval.py --case case_005    # evaluate one case
    python evaluation/run_eval.py --report           # generate markdown report

Requires:
    DEEPSEEK_API_KEY in .env (for LLM judge)
    Agent response files in evaluation/responses/ or use --live mode
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from evaluation.criterion import DIMENSION_CRITERIA, dimension_to_score, total_score
from evaluation.llm_judge import LLMJudge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GOLDEN_DIR = Path(__file__).resolve().parent / "golden_cases"
RESPONSES_DIR = Path(__file__).resolve().parent / "responses"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
for d in [REPORTS_DIR, RESULTS_DIR, RESPONSES_DIR]:
    d.mkdir(exist_ok=True)


def load_cases() -> list[dict]:
    """Load all Golden Case YAML files."""
    cases = []
    for path in sorted(GOLDEN_DIR.glob("case_*.yaml")):
        with open(path, encoding="utf-8") as f:
            cases.append(yaml.safe_load(f))
    return cases


def load_response_file(case_id: str) -> str | None:
    """Load a pre-recorded agent response from evaluation/responses/."""
    path = RESPONSES_DIR / f"{case_id}_response.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def save_response_file(case_id: str, response: str) -> str:
    """Save an agent response for later evaluation."""
    RESPONSES_DIR.mkdir(exist_ok=True)
    path = RESPONSES_DIR / f"{case_id}_response.md"
    path.write_text(response, encoding="utf-8")
    return str(path)


def evaluate_case(case: dict, judge: LLMJudge) -> dict:
    """Evaluate a single Golden Case against the agent response."""
    case_id = case["id"]
    query = case["input"]["content"]
    expected = case["expected"]

    # Try to load pre-recorded response
    response = load_response_file(case_id)
    if response is None:
        logger.error("No pre-recorded response for %s. Run agent first, save to evaluation/responses/%s_response.md",
                     case_id, case_id)
        return {"error": "no_response_file", "case_id": case_id}

    logger.info("Evaluating %s: %s", case_id, case["title"])
    logger.info("  Query: %s...", query[:100])
    logger.info("  Response: %d chars", len(response))

    result = judge.evaluate_response(query=query, response=response)

    # Add case metadata
    result["case_id"] = case_id
    result["skill"] = case.get("skill", "")
    result["title"] = case["title"]
    result["difficulty"] = case.get("difficulty", "")
    result["evaluated_at"] = datetime.now(timezone.utc).isoformat()

    # Compare against expected assertions
    expected_assertions = expected.get("output_assertions", [])
    assertion_results = []
    for assertion in expected_assertions:
        try:
            # Simple checks for now
            if "长度 >=" in assertion:
                parts = assertion.split("长度 >=")
                key = parts[0].replace("output.", "").strip()
                min_len = int(parts[1].strip())
                actual_len = len(response)
                assertion_results.append({
                    "assertion": assertion,
                    "passed": actual_len >= min_len,
                    "detail": f"response length {actual_len} >= {min_len}"
                })
            else:
                assertion_results.append({"assertion": assertion, "passed": None, "detail": "manual check required"})
        except Exception:
            assertion_results.append({"assertion": assertion, "passed": None, "detail": "parse error"})

    result["assertions"] = assertion_results
    return result


def generate_report(results: list[dict]) -> str:
    """Generate a markdown evaluation report."""
    lines = [
        f"# CagentOS Evaluation Report",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Cases evaluated: {len(results)}",
        "",
        "## Summary",
        "",
        "| # | Case | Skill | Difficulty | Score | Pass? |",
        "|---|------|-------|-----------|------|------|",
    ]

    passed_count = 0
    total_scored = 0
    for r in results:
        if "error" in r:
            lines.append(f"| {r['case_id']} | {r.get('title','?')[:40]} | ? | ? | ERR | ❌ |")
            continue
        score = r.get("total_score", 0)
        passed = r.get("passed", False)
        if passed:
            passed_count += 1
        total_scored += 1
        lines.append(
            f"| {r['case_id']} | {r['title'][:40]} | {r['skill']} | {r['difficulty']} | "
            f"{score}/24 | {'✅' if passed else '❌'} |"
        )

    if total_scored > 0:
        pct = passed_count / total_scored * 100
        lines.append(f"\n**Pass rate: {passed_count}/{total_scored} ({pct:.0f}%)** (threshold: 18/24)")

    # Dimension breakdown
    lines.append("\n## Dimension Scores\n")
    dim_totals = {}
    for r in results:
        if "error" in r:
            continue
        for dim, score in r.get("scores", {}).items():
            if dim not in dim_totals:
                dim_totals[dim] = []
            dim_totals[dim].append(score)

    for dim, scores in sorted(dim_totals.items()):
        avg = sum(scores) / len(scores) if scores else 0
        lines.append(f"- **{dim}**: avg {avg:.1f}/4 ({len(scores)} cases)")

    # Per-case details
    lines.append("\n## Per-Case Details\n")
    for r in results:
        if "error" in r:
            lines.append(f"### {r['case_id']}: {r.get('title','?')}")
            lines.append(f"**ERROR**: {r['error']}\n")
            continue

        lines.append(f"### {r['case_id']}: {r['title']}")
        lines.append(f"**Score**: {r['total_score']}/24 ({'PASS' if r['passed'] else 'FAIL'})")
        lines.append(f"**Criteria**: {r['criteria_passed']}/{r['criteria_checked']} passed\n")

        for detail in r.get("details", []):
            status = "✅" if detail["satisfied"] else "❌"
            lines.append(f"- {status} {detail['criterion_id']}: {detail.get('evidence', 'no evidence')[:120]}")

        # Assertions
        assertions = r.get("assertions", [])
        if assertions:
            lines.append("\n**Output Assertions:**")
            for a in assertions:
                passed = a.get("passed")
                if passed is True:
                    lines.append(f"- ✅ {a['assertion']}")
                elif passed is False:
                    lines.append(f"- ❌ {a['assertion']}")
                else:
                    lines.append(f"- ⬜ {a['assertion']} (manual)")
        lines.append("")

    report = "\n".join(lines)
    return report


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="CagentOS Golden Case Evaluator")
    parser.add_argument("--case", type=str, help="Evaluate a single case by id (e.g. case_005)")
    parser.add_argument("--report", action="store_true", help="Generate markdown report")
    parser.add_argument("--save-report", action="store_true", help="Save report to evaluation/reports/")
    parser.add_argument("--save-json", action="store_true", help="Save structured results to evaluation/results/")
    parser.add_argument("--compare", type=str, nargs=2, metavar=("FILE1", "FILE2"), help="Compare two JSON result files")
    parser.add_argument("--dashboard", action="store_true", help="Show dashboard from last saved results")
    args = parser.parse_args()

    # ── Compare mode ──
    if args.compare:
        f1, f2 = args.compare
        _compare_results(f1, f2)
        return

    # ── Dashboard mode ──
    if args.dashboard:
        _show_dashboard()
        return

    # ── Evaluation mode ──
    judge = LLMJudge()
    cases = load_cases()

    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"Case {args.case} not found")
            sys.exit(1)

    print(f"Evaluating {len(cases)} case(s)...")
    results = []
    for case in cases:
        result = evaluate_case(case, judge)
        results.append(result)
        if "error" not in result:
            print(f"  {case['id']}: {result['total_score']}/24 "
                  f"({'PASS' if result['passed'] else 'FAIL'}) "
                  f"({result['criteria_passed']}/{result['criteria_checked']} criteria)")
        else:
            print(f"  {case['id']}: ERROR — {result['error']}")

    # Print dimension breakdown
    print("\nDimension Averages:")
    dim_totals = {}
    for r in results:
        if "error" in r:
            continue
        for dim, score in r.get("scores", {}).items():
            dim_totals.setdefault(dim, []).append(score)
    for dim, scores in sorted(dim_totals.items()):
        avg = sum(scores) / len(scores) if scores else 0
        print(f"  {dim:12s}: {avg:.1f}/4")

    # JSON save
    if args.save_json:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = RESULTS_DIR / f"eval_{ts}.json"
        json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON saved: {json_path}")

        # Also update "latest" symlink-like file
        latest_path = RESULTS_DIR / "latest.json"
        latest_path.write_text(json_path.name, encoding="utf-8")
        print(f"Updated: {latest_path} -> {json_path.name}")

    # Report
    if args.report or args.save_report:
        report = generate_report(results)
        if args.save_report:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = REPORTS_DIR / f"eval_report_{ts}.md"
            report_path.write_text(report, encoding="utf-8")
            print(f"\nReport saved: {report_path}")
        if args.report:
            print(f"\n{report}")


def _compare_results(f1: str, f2: str) -> None:
    """Compare two JSON result files and show regressions/improvements."""
    d1 = json.loads(Path(f1).read_text(encoding="utf-8"))
    d2 = json.loads(Path(f2).read_text(encoding="utf-8"))

    print(f"Comparing: {Path(f1).name} vs {Path(f2).name}\n")
    print(f"{'Case':<15} {'Prev':>6} {'Curr':>6} {'Delta':>7} {'Status'}")
    print("-" * 50)

    improved = 0
    regressed = 0
    unchanged = 0

    for r1, r2 in zip(d1, d2):
        if "error" in r1 or "error" in r2:
            continue
        s1 = r1.get("total_score", 0)
        s2 = r2.get("total_score", 0)
        delta = s2 - s1
        if delta > 0:
            status = ">> IMPROVED"
            improved += 1
        elif delta < 0:
            status = f"<< REGRESSED ({delta})"
            regressed += 1
        else:
            status = "-- unchanged"
            unchanged += 1
        print(f"{r1['case_id']:<15} {s1:>4}/24 {s2:>4}/24 {delta:+7} {status}")

    print(f"\nSummary: {improved} improved, {regressed} regressed, {unchanged} unchanged")

    # Dimension-level comparison
    print("\nDimension Changes:")
    for dim in ["task", "facts", "tools", "reasoning", "risk", "format"]:
        avg1 = sum(r.get("scores", {}).get(dim, 0) for r in d1 if "error" not in r) / max(1, len(d1))
        avg2 = sum(r.get("scores", {}).get(dim, 0) for r in d2 if "error" not in r) / max(1, len(d2))
        delta = avg2 - avg1
        status = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        print(f"  {dim:12s}: {avg1:.1f} → {avg2:.1f} ({delta:+.1f}) {status}")


def _show_dashboard() -> None:
    """Show dashboard from the most recent saved results."""
    latest_file = RESULTS_DIR / "latest.json"
    if not latest_file.exists():
        print("No saved results yet. Run with --save-json first.")
        return

    # Read the filename pointed to by latest
    actual_name = latest_file.read_text(encoding="utf-8").strip()
    actual_path = RESULTS_DIR / actual_name
    if not actual_path.exists():
        print(f"Latest result file not found: {actual_path}")
        return

    results = json.loads(actual_path.read_text(encoding="utf-8"))

    print(f"\n{'=' * 70}")
    print(f"  CagentOS Evaluation Dashboard")
    print(f"  Source: {actual_name}")
    print(f"  Generated: {results[0].get('evaluated_at', '?')[:19] if results else '?'}")
    print(f"{'=' * 70}\n")

    # Score table
    print(f"{'Case':<15} {'Score':>6} {'Pass?':>6} {'Criteria':>10}  {'Skill'}")
    print("-" * 70)
    total_score_sum = 0
    passed_count = 0
    valid = 0
    for r in results:
        if "error" in r:
            print(f"{r['case_id']:<15} {'ERR':>6} {'-':>6} {'-':>10}  {r.get('skill','?')}")
            continue
        s = r.get("total_score", 0)
        p = r.get("passed", False)
        c = f"{r.get('criteria_passed',0)}/{r.get('criteria_checked',0)}"
        total_score_sum += s
        valid += 1
        if p: passed_count += 1
        print(f"{r['case_id']:<15} {s:>4}/24 {'PASS' if p else 'FAIL':>6} {c:>10}  {r.get('skill','?')}")

    if valid > 0:
        avg = total_score_sum / valid
        pct = passed_count / valid * 100
        print(f"\n  Average: {avg:.1f}/24  |  Pass rate: {passed_count}/{valid} ({pct:.0f}%)")

    # Dimension heatmap
    print(f"\n{'Dimension':<12}", end="")
    for r in results:
        if "error" not in r:
            print(f"  {r['case_id']}", end="")
    print()

    dims = ["task", "facts", "tools", "reasoning", "risk", "format"]
    for dim in dims:
        print(f"{dim:<12}", end="")
        for r in results:
            if "error" in r:
                continue
            score = r.get("scores", {}).get(dim, 0)
            # Simple color: 4=██, 3=▓▓, 2=▒▒, 1=░░, 0=··
            bar = ["..", "::", "==", "##", "XX"][score]
            print(f"  {bar}", end="")
        print()

    # Timeline if multiple files exist
    print("\nHistory:")
    result_files = sorted(RESULTS_DIR.glob("eval_*.json"))
    if len(result_files) > 1:
        for rf in result_files[-10:]:
            data = json.loads(rf.read_text(encoding="utf-8"))
            scores = [r.get("total_score", 0) for r in data if "error" not in r]
            avg = sum(scores) / len(scores) if scores else 0
            marker = " ⬅ current" if rf.name == actual_name else ""
            print(f"  {rf.stem}: avg {avg:.1f}/24 ({len(scores)} cases){marker}")
    else:
        print("  (only one result file — run again after changes to build history)")


if __name__ == "__main__":
    main()
