"""Golden Case scorer — simple manual evaluation checklist.

Phase 2c: Manual scoring. Phase 3+: Automate with DeepEval.

Usage:
    python evaluation/golden_cases/scorer.py

This prints a scoring worksheet. You fill in scores manually based on
the agent's actual output for each Golden Case.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml  # pip install pyyaml (already in project deps)

GOLDEN_DIR = Path(__file__).resolve().parent

DIMENSIONS = ["task", "facts", "tools", "reasoning", "risk", "format"]
WEIGHTS = {"task": 20, "facts": 20, "tools": 15, "reasoning": 25, "risk": 10, "format": 10}
PASS_THRESHOLD = 18  # out of 24


def load_cases() -> list[dict]:
    cases = []
    for path in sorted(GOLDEN_DIR.glob("case_*.yaml")):
        with open(path, encoding="utf-8") as f:
            cases.append(yaml.safe_load(f))
    return cases


def print_worksheet(case: dict) -> None:
    print(f"\n{'=' * 70}")
    print(f"  Case: {case['id']} — {case['title']}")
    print(f"  Skill: {case['skill']}  |  Difficulty: {case['difficulty']}")
    print(f"{'=' * 70}")
    print(f"\n  SCENARIO: {case['scenario'][:200]}")
    print(f"\n  EXPECTED TASK: {case['expected']['task'][:300]}")

    print(f"\n  CRITICAL FACTS (must appear):")
    for f in case["expected"]["critical_facts"]:
        print(f"    [ ] {f}")

    print(f"\n  MUST USE TOOLS:")
    for t in case["expected"]["must_use_tools"]:
        print(f"    [ ] {t}")

    print(f"\n  MUST NOT:")
    for m in case["expected"]["must_not_do"]:
        print(f"    [ ] {m}")

    print(f"\n  SCORING (0-4 each):")
    total = 0
    for dim in DIMENSIONS:
        rubric = case["rubric"].get(dim, {})
        note = rubric.get("note", "")
        print(f"    [{dim:12s}] __ / 4   ({WEIGHTS[dim]}%)  {note[:80]}")
    print(f"\n  TOTAL: __ / 24  (pass >= {PASS_THRESHOLD})")
    print(f"  PASS: [ ] YES  [ ] NO")
    print()


def main() -> None:
    cases = load_cases()
    if not cases:
        print("No golden cases found in", GOLDEN_DIR)
        sys.exit(1)

    print(f"\n  Golden Cases Evaluator — {len(cases)} cases loaded")
    print(f"  Pass threshold: {PASS_THRESHOLD}/24")
    print(f"  Instructions: Run each case through the agent, then fill in scores.")

    for case in cases:
        print_worksheet(case)

    # Summary
    print(f"\n{'=' * 70}")
    print(f"  SUMMARY")
    print(f"{'=' * 70}")
    for case in cases:
        print(f"  {case['id']}: {case['title'][:60]}")
    print(f"\n  Run: python evaluation/golden_cases/scorer.py")
    print(f"  To add a case: cp case_001_triage.yaml case_004_xxx.yaml && edit")


if __name__ == "__main__":
    main()
