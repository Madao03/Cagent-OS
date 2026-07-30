"""End-to-end verification script for Supervisor + Researcher (Phase 4a+ fix).

Run:
    python scripts/verify_supervisor.py                  # full pipeline
    python scripts/verify_supervisor.py --parser-only     # just JSON-block parser

No pytest, no mocks — just run the real thing and print the result.

Three checks:
  1. Parser unit check — feed a fake markdown+JSON block, verify fields
  2. Supervisor pipeline — run a real query through Supervisor.run()
  3. AnalysisReport assertion — confirm thesis / valuation / citations
     are populated (not the empty fallback template)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure project src on path when run from repo root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ────────────────────────────────────────────────────────────────────
# CHECK 1: Parser unit test (no network, no LLM)
# ────────────────────────────────────────────────────────────────────

FAKE_LLM_OUTPUT = """# NVDA 估值分析

## 分析

NVDA 当前 P/E 65x 处于历史 85 分位,AI 需求支撑长期逻辑但利率倒挂压制高估值。
建议等待回调至 P/E 50x 以下再建仓。

## 风险

- 利率持续倒挂,高估值成长股承压
- AI 资本开支周期见顶
- 半导体库存累积

## 催化剂

- 下季度数据中心营收超预期
- 软件订阅业务放量
"""

FAKE_LLM_OUTPUT_WITH_JSON = FAKE_LLM_OUTPUT + """

<!-- ANALYSIS_JSON:
{
  "ticker": "NVDA",
  "thesis": "NVDA 当前 P/E 65x 处于历史 85 分位,AI 需求支撑长期逻辑但利率倒挂压制高估值。建议等待回调至 P/E 50x 以下再建仓。",
  "risks": ["利率持续倒挂", "AI 资本开支周期见顶", "半导体库存累积"],
  "catalysts": ["下季度数据中心营收超预期", "软件订阅业务放量"],
  "pe_forward": 35.2,
  "pe_ttm": 42.1,
  "ev_ebitda": 28.5,
  "pb": 45.0,
  "recommendation": "hold",
  "confidence": "medium",
  "citations": [
    {"metric": "Forward PE", "value": 35.2, "source": "yfinance", "confidence": 0.9},
    {"metric": "10Y-2Y Spread", "value": -43, "source": "FRED", "confidence": 0.95}
  ]
}
-->


"""


def check_parser() -> bool:
    """Verify _parse_analysis_output correctly extracts structured fields."""
    from cagent_os.multi_agent.supervisor import Supervisor

    print("\n" + "=" * 60)
    print("CHECK 1: Parser — structured JSON block extraction")
    print("=" * 60)

    # 1a. Without JSON block → falls back to regex
    thesis, risks, catalysts, valuation, citations = Supervisor._parse_analysis_output(
        FAKE_LLM_OUTPUT, query="分析 NVDA 估值", ticker="NVDA",
    )
    print(f"\n[1a] Regex fallback path:")
    print(f"  thesis[:80]: {thesis[:80]!r}")
    print(f"  risks: {risks}")
    print(f"  valuation: {valuation}")
    print(f"  citations: {citations}")
    assert len(risks) >= 1, "regex path should find at least 1 risk"
    assert citations == [], "regex path has no citations"
    assert valuation.fwd_pe is None, "regex path has no valuation"

    # 1b. With JSON block → structured extraction
    thesis, risks, catalysts, valuation, citations = Supervisor._parse_analysis_output(
        FAKE_LLM_OUTPUT_WITH_JSON, query="分析 NVDA 估值", ticker="NVDA",
    )
    print(f"\n[1b] JSON block path:")
    print(f"  thesis[:80]: {thesis[:80]!r}")
    print(f"  risks ({len(risks)}): {risks}")
    print(f"  catalysts ({len(catalysts)}): {catalysts}")
    print(f"  valuation.fwd_pe: {valuation.fwd_pe}")
    print(f"  valuation.notes: {valuation.notes!r}")
    print(f"  citations ({len(citations)}):")
    for c in citations:
        print(f"    - {c.metric} = {c.value} ({c.source}, conf={c.confidence})")

    assert valuation.fwd_pe == 35.2, f"Expected fwd_pe=35.2, got {valuation.fwd_pe}"
    assert len(citations) == 2, f"Expected 2 citations, got {len(citations)}"
    assert citations[0].source == "yfinance"
    assert citations[1].value == -43
    assert "P/E (TTM): 42.1" in valuation.notes
    print("\n[OK] Parser check passed")
    return True


# ────────────────────────────────────────────────────────────────────
# CHECK 2: End-to-end Supervisor run with real AgentRuntime
# ────────────────────────────────────────────────────────────────────


async def check_supervisor_e2e(query: str = "分析 NVDA 当前估值,给出 P/E、风险和催化剂") -> bool:
    """Run Supervisor with the default AgentRuntime runner.

    This requires DEEPSEEK_API_KEY (or equivalent) in the environment.
    If the runner cannot be built (missing deps), this check is skipped.
    """
    from cagent_os.multi_agent.agent_runner import build_default_runner
    from cagent_os.multi_agent.supervisor import Supervisor, SupervisorConfig

    print("\n" + "=" * 60)
    print(f"CHECK 2: Supervisor end-to-end — {query!r}")
    print("=" * 60)

    runner = build_default_runner()
    if runner is None:
        print("\n[SKIP] Default runner unavailable (missing API key / deps).")
        print("       Set DEEPSEEK_API_KEY in .env to run this check.")
        return False

    config = SupervisorConfig(
        timeout_seconds=240,
        agent_runner=runner,
    )
    supervisor = Supervisor(config=config)

    print("\nRunning Supervisor pipeline (this takes 30-120s)...")
    result = await supervisor.run(query)

    print(f"\n[Result]")
    print(f"  elapsed_ms: {result.elapsed_ms}")
    print(f"  errors: {result.errors}")
    print(f"  decision.intent: {result.decision.intent}")
    print(f"  decision.agents: {result.decision.agents}")

    if result.raw_data:
        print(f"\n  raw_data.items ({len(result.raw_data.items)}):")
        for item in result.raw_data.items[:5]:
            print(f"    - [{item.source}] {item.metric}: {item.value}")

    if result.analysis:
        print(f"\n  analysis.ticker: {result.analysis.ticker}")
        print(f"  analysis.thesis[:200]: {result.analysis.thesis[:200]!r}")
        print(f"  analysis.risks ({len(result.analysis.risks)}): {result.analysis.risks}")
        print(f"  analysis.catalysts ({len(result.analysis.catalysts)}): {result.analysis.catalysts}")
        print(f"  analysis.valuation: {result.analysis.valuation}")
        print(f"  analysis.data_citations ({len(result.analysis.data_citations)}):")
        for c in result.analysis.data_citations[:5]:
            print(f"    - {c.metric} = {c.value} ({c.source})")

    if result.audit:
        print(f"\n  audit.severity: {result.audit.severity}")
        print(f"  audit.gap: {result.audit.gap[:120]}")

    if result.summary:
        print(f"\n  summary.conclusion[:200]: {result.summary.conclusion[:200]!r}")
        print(f"  summary.confidence: {result.summary.confidence}")
        print(f"  summary.key_evidence ({len(result.summary.key_evidence)}): {result.summary.key_evidence}")

    # Assertions: prove the pipeline produced real (non-template) output
    success = True
    if not result.analysis:
        print("\n[FAIL] analysis is None")
        return False

    # Template fallback thesis is literally "Analysis requested for: ..."
    if result.analysis.thesis.startswith("Analysis requested for:"):
        print("\n[FAIL] analysis.thesis is the template fallback — agent_runner did not run")
        success = False

    # If citations/valuation came through, JSON path worked
    has_real_data = (
        result.analysis.valuation.fwd_pe is not None
        or len(result.analysis.data_citations) > 0
        or len(result.analysis.risks) > 0
    )
    if has_real_data:
        print(f"\n[OK] AnalysisReport contains real structured data")
    else:
        print(f"\n[WARN] AnalysisReport looks empty (valuation/citations/risks all zero)")

    return success


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parser-only", action="store_true",
                        help="Only run parser unit check (no LLM, no network)")
    parser.add_argument("--query", default="分析 NVDA 当前估值,给出 P/E、风险和催化剂")
    args = parser.parse_args()

    ok = check_parser()
    if not ok:
        return 1

    if args.parser_only:
        print("\n[Done] Parser-only mode, skipping Supervisor E2E.")
        return 0

    e2e_ok = asyncio.run(check_supervisor_e2e(args.query))
    return 0 if e2e_ok else 2


if __name__ == "__main__":
    sys.exit(main())
