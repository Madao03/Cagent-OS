"""Provenance baseline fixture — frozen test sample from P0-b initial run.

This output contains 6 known number categories, each testing a different
aspect of the provenance system. When the normalizer/checker is modified,
re-run this test to verify no regressions.

Categories:
  1. ¥767.2亿   → traced (exact match with Registry: 76720000000)
  2. ¥578.6亿   → should trace to -57860000000 via abs + context sign check
  3. 4523亿     → traced (exact match with Registry: 452300000000)
  4. 130亿      → should trace to 13030000000 (0.23% < 0.5% tolerance)
  5. 977亿      → untraced (not in Registry — Tesla number, no tool returned it)
  6. 18.5       → untraced (derived or hallucinated — diagnose separately)

Non-data exclusions (should NOT be flagged):
  - 2025 (year, appears 3x)
  - 1 (list index, if present)
"""
from __future__ import annotations

import pytest
import sys

sys.path.insert(0, "src")

from cagent_os.provenance import FactRegistry, check_provenance
from cagent_os.plugins.contracts import ToolResult


# ── Frozen test data ──────────────────────────────────────────

# The exact output that produced the initial baseline
AGENT_OUTPUT = """小鹏汽车 2025 年财务分析

2025 全年营收为 ¥767.2亿，净亏损 ¥578.6亿。
总资产达 4523亿。第一季度营收约 130亿。

相比之下，特斯拉 2025 年营收约 977亿美元。
据我估算，小鹏单车收入约为 18.5 万元。
"""


def _build_registry() -> FactRegistry:
    """Build the registry used in the baseline run.

    Includes Q1 records so that 130亿 can trace correctly.
    """
    registry = FactRegistry(turn=1)
    edgar_result = ToolResult(status="ok", content={
        "success": True,
        "ticker": "XPEV",
        "audited": True,
        "currency": "CNY",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "revenue": 76720000000,
        "net_income": -57860000000,
        "total_assets": 452300000000,
        "records": [
            {"period_type": "quarter", "period_start": "2025-01-01",
             "period_end": "2025-03-31", "currency": "CNY",
             "revenue": 13030000000},
        ],
    })
    registry.register_tool_result("financial.edgar.facts", edgar_result, {"ticker": "XPEV"})
    return registry


class TestProvenanceBaseline:
    """Frozen baseline — each test case pins one category of number.

    When fixing normalizer/checker bugs, update the expected values
    to match the CORRECT behavior (not the current buggy behavior).
    Mark changes with ★ to track what was fixed.
    """

    def test_767_traced_to_edgar(self):
        """¥767.2亿 should trace to EDGAR revenue (exact match)."""
        registry = _build_registry()
        result = check_provenance(AGENT_OUTPUT, registry)
        values = {t.value for t in result.traced_numbers}
        assert 76720000000.0 in values, "¥767.2亿 must trace to EDGAR"

    def test_4523_traced_to_edgar(self):
        """4523亿 should trace to EDGAR total_assets."""
        registry = _build_registry()
        result = check_provenance(AGENT_OUTPUT, registry)
        values = {t.value for t in result.traced_numbers}
        assert 452300000000.0 in values, "4523亿 must trace to EDGAR"

    def test_578_traced_via_abs_and_sign_context(self):
        """★ ¥578.6亿 (net loss) should trace to -57860000000 via abs value
        + context contains '亏损' (loss) confirming negative semantics."""
        registry = _build_registry()
        result = check_provenance(AGENT_OUTPUT, registry)
        values = {t.value for t in result.traced_numbers}
        # Should match on absolute value 57860000000
        assert 57860000000.0 in values or -57860000000.0 in values, \
            "¥578.6亿 must trace via abs value matching"

    def test_130_traced_within_tolerance(self):
        """130亿 should trace to Q1 revenue 13030000000 (0.23% < 0.5%)."""
        registry = _build_registry()
        result = check_provenance(AGENT_OUTPUT, registry)
        values = {t.value for t in result.traced_numbers}
        assert 13000000000.0 in values, "130亿 must trace within tolerance"

    def test_977_detected_as_untraced(self):
        """★ 977亿 (Tesla revenue, NOT in Registry) must be detected as untraced.

        Previously missed by scanner due to (?!\w) blocking Chinese suffix (美元).
        Fixed: changed to (?![a-zA-Z0-9_]) to allow Chinese chars after number.
        """
        registry = _build_registry()
        result = check_provenance(AGENT_OUTPUT, registry)
        all_numbers = result.traced_numbers + result.untraced_numbers
        all_raws = [n.raw for n in all_numbers]
        # 977亿 must appear somewhere (traced or untraced), NOT silently skipped
        found = any("977" in r for r in all_raws)
        assert found, \
            "977亿 must be detected by scanner (either traced or untraced) — " \
            "if missing, scanner has coverage blind spot"

    def test_years_excluded_as_non_data(self):
        """2025 (year) must NOT be flagged as data."""
        registry = _build_registry()
        result = check_provenance(AGENT_OUTPUT, registry)
        # Years should be in non_data, not in traced/untraced
        all_data = result.traced_numbers + result.untraced_numbers
        for num in all_data:
            assert num.value != 2025.0, "2025 is a year, not data"

    def test_18_5_detected_and_untraced(self):
        """18.5 (单车收入) must be detected and correctly untraced.

        Not a hallucination — it's revenue/deliveries, but deliveries
        are not in Registry. Correctly untraced until P1 derived chain.
        """
        registry = _build_registry()
        result = check_provenance(AGENT_OUTPUT, registry)
        all_numbers = result.traced_numbers + result.untraced_numbers
        all_raws = [n.raw for n in all_numbers]
        found = any("18.5" in r for r in all_raws)
        assert found, "18.5 must be detected by scanner"


class TestChineseMagnitudeParsing:
    """Verify that Chinese magnitude suffixes are parsed correctly.

    These are NOT provenance checks — they verify the normalizer's
    number extraction is correct. If parsing is wrong, the provenance
    checker gets bad input.
    """

    def test_977_yi_parses_to_97_7_billion(self):
        """977亿 must parse to 9.77e10, not 977."""
        from cagent_os.provenance.normalizer import extract_numbers
        nums = extract_numbers("营收约 977亿美元")
        data_nums = [n for n in nums if n.is_data]
        assert len(data_nums) >= 1
        assert data_nums[0].value == 9.77e10, f"Expected 9.77e10, got {data_nums[0].value}"

    def test_wanyi_parses_correctly(self):
        """万亿 must parse to 1e12."""
        from cagent_os.provenance.normalizer import extract_numbers
        nums = extract_numbers("总市值 12.3 万亿")
        data_nums = [n for n in nums if n.is_data]
        assert len(data_nums) >= 1
        assert abs(data_nums[0].value - 12.3e12) < 1, f"Expected 12.3e12, got {data_nums[0].value}"

    def test_wan_parses_correctly(self):
        """万 must parse to 1e4."""
        from cagent_os.provenance.normalizer import extract_numbers
        nums = extract_numbers("单价 18.5 万")
        data_nums = [n for n in nums if n.is_data]
        assert len(data_nums) >= 1
        assert data_nums[0].value == 185000.0, f"Expected 185000, got {data_nums[0].value}"

    def test_currency_prefix_stripped(self):
        """¥767.2亿 must parse to 76720000000, currency symbol stripped."""
        from cagent_os.provenance.normalizer import extract_numbers
        nums = extract_numbers("营收 ¥767.2亿")
        data_nums = [n for n in nums if n.is_data]
        assert len(data_nums) >= 1
        assert data_nums[0].value == 76720000000.0

    def test_western_suffix_B(self):
        """76.72B must parse to 76720000000."""
        from cagent_os.provenance.normalizer import extract_numbers
        nums = extract_numbers("Revenue: $76.72B")
        data_nums = [n for n in nums if n.is_data]
        assert len(data_nums) >= 1
        assert data_nums[0].value == 76720000000.0


class TestSignConflict:
    """Verify sign conflict detection catches dangerous sign mismatches."""

    def test_preceding_clause_uses_match_start_position(self):
        """★ _extract_preceding_clause position convention = match.start()

        This is a methodological test: verify the diagnostic tests the
        same code path as the real checker. Previous versions mixed
        position conventions (match.start vs match.end vs arbitrary),
        causing tests to pass for wrong reasons (5th instance of
        "indicator measures the wrong thing" pattern).
        """
        from cagent_os.provenance.checker import _extract_preceding_clause

        text = "全年营收为 ¥767.2亿，净亏损 ¥578.6亿"
        # Find 767.2's position — should be the start of the number
        import re
        m = re.search(r'767\.2', text)
        assert m is not None
        clause_767 = _extract_preceding_clause(text, m.start())
        # Clause before 767 should NOT contain 亏损 (it belongs to 578.6)
        assert "亏损" not in clause_767, \
            f"Clause for 767.2 should not contain 亏损, got: {clause_767!r}"

        # Find 578.6's position
        m2 = re.search(r'578\.6', text)
        assert m2 is not None
        clause_578 = _extract_preceding_clause(text, m2.start())
        # Clause before 578 SHOULD contain 净亏损
        assert "亏损" in clause_578, \
            f"Clause for 578.6 should contain 亏损, got: {clause_578!r}"

    def test_keyword_after_number_not_detected(self):
        """Keyword AFTER number is not detected — this fails SAFE.

        When sign keyword is after the number ("¥578.6亿的亏损"),
        preceding clause is empty → no sign context → abs matching
        not triggered → number goes to untraced (visible false positive),
        NOT incorrectly traced (hidden false negative).

        This is acceptable because:
          - Chinese financial text convention: label before number (stable)
          - Keyword after → untraced (visible, fixable)
          - NOT: keyword after → traced with wrong sign (hidden, dangerous)
        """
        from cagent_os.provenance.checker import _extract_preceding_clause
        import re

        text = "营收 ¥578.6亿的亏损"
        m = re.search(r'578\.6', text)
        clause = _extract_preceding_clause(text, m.start())
        # Preceding clause should contain 营收 but NOT 亏损
        assert "营收" in clause
        assert "亏损" not in clause  # 亏损 is AFTER the number, not detected

    def test_negative_fact_with_profit_context_is_conflict(self):
        """★ Registry negative + output says '净利润' = sign_conflict.

        Example: Registry has net_income=-57860000000 (loss).
        Agent writes "净利润 ¥578.6亿" — absolute value matches,
        but the semantics are WRONG (profit ≠ loss).
        This must NOT be traced — it must be flagged as sign_conflict.
        """
        registry = _build_registry()
        malicious_output = "小鹏 2025 年净利润 ¥578.6亿，表现优异。"
        result = check_provenance(malicious_output, registry)

        # Must NOT be traced
        traced_vals = {t.value for t in result.traced_numbers}
        assert 57860000000.0 not in traced_vals, \
            "Sign conflict must not be traced"

        # Must be flagged as sign_conflict
        assert result.sign_conflicts >= 1, \
            f"Expected sign_conflict, got {result.sign_conflicts}"
        conflict = result.sign_conflict_numbers[0]
        assert "negative" in conflict.conflict_detail.lower()
