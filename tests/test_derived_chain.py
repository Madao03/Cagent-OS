"""P1 Derived Chain tests — formula verification + inheritance + rejection rules.

Includes accounting_standard cross-standard rejection (#6) with four
explicit combinations to prevent silent breakage from field default changes.
"""
from __future__ import annotations

import pytest
import sys

sys.path.insert(0, "src")

from cagent_os.provenance.fact_registry import Fact, FactRegistry
from cagent_os.provenance.derived_chain import (
    extract_derivations_block, verify_derivations, register_derived_facts,
)


def _make_fact(reg: FactRegistry, caliber: str, value: float,
               period_end: str = "2025-12-31", period_type: str = "quarter",
               currency: str = "CNY", accounting_standard: str = "",
               audited: bool | None = None, precision: str = "") -> Fact:
    """Helper: create and register a fact."""
    f = Fact(
        id=reg.next_id(), kind="data", value=value, caliber=caliber,
        period_end=period_end, period_type=period_type,
        currency=currency, accounting_standard=accounting_standard,
        audited=audited, precision=precision,
    )
    reg._facts.append(f)
    return f


def _parse_and_verify(output_text: str, reg: FactRegistry):
    """Helper: extract block, verify, return derivation result."""
    _, dr = extract_derivations_block(output_text)
    assert dr is not None, "Derivation block not found"
    verify_derivations(dr, reg)
    return dr


# ── accounting_standard: three-state semantics ───────────────

class TestAccountingStandardCombinations:
    """accounting_standard: three-state semantics.

    "" (absent)    → not applicable — skip conflict check
    "UNKNOWN"      → data gap — flag (warn), don't reject
    "CAS" / "US_GAAP" / "IFRS" → specific — participate in conflict

    null + US_GAAP is a valid ratio (e.g., PE = market_cap / net_income).
    UNKNOWN + US_GAAP: specific wins, no rejection.
    """

    def test_null_plus_null_passes(self):
        """MVRV: market_cap (null) / realized_cap (null) — both non-accounting."""
        reg = FactRegistry(turn=0)
        _make_fact(reg, "market_cap", 1e11, accounting_standard="")
        _make_fact(reg, "realized_cap", 5e10, accounting_standard="")
        output = "test\n[derivations]\nf:0:1 / f:0:2 = 2.0\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 1, "null+null should pass"
        assert dr.error_count == 0
        assert dr.warning_count == 0

    def test_null_plus_usgaap_passes(self):
        """PE ratio: market_cap (null) / net_income (US_GAAP) — valid."""
        reg = FactRegistry(turn=0)
        _make_fact(reg, "market_cap", 1e11, accounting_standard="")
        _make_fact(reg, "net_income", 5e8, accounting_standard="US_GAAP", audited=True)
        output = "test\n[derivations]\nmarket_cap@2025Q4 / net_income@2025Q4 = 200\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 1, "null+US_GAAP should pass (PE is valid)"
        assert dr.error_count == 0
        assert dr.warning_count == 0

    def test_usgaap_plus_usgaap_passes(self):
        """Net margin: net_income / revenue — both US_GAAP."""
        reg = FactRegistry(turn=0)
        _make_fact(reg, "net_income", 5e8, accounting_standard="US_GAAP", audited=True)
        _make_fact(reg, "revenue", 2.2e10, accounting_standard="US_GAAP", audited=True)
        output = "test\n[derivations]\nnet_income@2025Q4 / revenue@2025Q4 = 0.0229\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 1, "US_GAAP+US_GAAP should pass"
        assert dr.error_count == 0
        assert dr.warning_count == 0

    def test_cas_plus_usgaap_rejected(self):
        """Cross-standard: CAS net_income / US_GAAP revenue — reject."""
        reg = FactRegistry(turn=0)
        _make_fact(reg, "net_income", 5e8, accounting_standard="CAS")
        _make_fact(reg, "revenue", 2.2e10, accounting_standard="US_GAAP", audited=True)
        output = "test\n[derivations]\nnet_income@2025Q4 / revenue@2025Q4 = 0.0229\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 0, "CAS+US_GAAP should be rejected"
        assert dr.error_count == 1
        assert "Accounting standard mismatch" in dr.errors[0]

    def test_unknown_plus_unknown_warns_but_passes(self):
        """★ Both UNKNOWN — flag but don't reject. We know standards exist
        but couldn't determine them. This is a data gap, not a contradiction."""
        reg = FactRegistry(turn=0)
        _make_fact(reg, "net_income", 5e8, accounting_standard="UNKNOWN")
        _make_fact(reg, "revenue", 2.2e10, accounting_standard="UNKNOWN")
        output = "test\n[derivations]\nnet_income@2025Q4 / revenue@2025Q4 = 0.0229\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 1, "UNKNOWN+UNKNOWN should still produce a result"
        assert dr.error_count == 0, "UNKNOWN+UNKNOWN should not be an error"
        assert dr.warning_count == 1, "UNKNOWN+UNKNOWN should warn"
        assert "unknown for all parents" in dr.warnings[0].lower()
        # Inherited standard should be UNKNOWN
        assert dr.verified[0].accounting_standard == "UNKNOWN"

    def test_unknown_plus_usgaap_specific_wins(self):
        """★ UNKNOWN + US_GAAP → US_GAAP wins. UNKNOWN means "couldn't
        determine" not "different standard". The specific value is trusted."""
        reg = FactRegistry(turn=0)
        _make_fact(reg, "net_income", 5e8, accounting_standard="UNKNOWN")
        _make_fact(reg, "revenue", 2.2e10, accounting_standard="US_GAAP", audited=True)
        output = "test\n[derivations]\nnet_income@2025Q4 / revenue@2025Q4 = 0.0229\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 1, "UNKNOWN+US_GAAP should pass"
        assert dr.error_count == 0
        assert dr.warning_count == 0, "Mixed UNKNOWN+specific → no warning needed"
        assert dr.verified[0].accounting_standard == "US_GAAP"

    def test_empty_plus_unknown_warns_once(self):
        """★ "" (not applicable) + UNKNOWN → UNKNOWN wins. The derivation
        inherits the standard that IS known to exist (even if undetermined)."""
        reg = FactRegistry(turn=0)
        _make_fact(reg, "market_cap", 1e11, accounting_standard="")
        _make_fact(reg, "net_income", 5e8, accounting_standard="UNKNOWN")
        output = "test\n[derivations]\nmarket_cap@2025Q4 / net_income@2025Q4 = 200\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 1, "null+UNKNOWN should pass"
        assert dr.error_count == 0
        assert dr.warning_count == 1, "UNKNOWN should trigger warning"
        assert dr.verified[0].accounting_standard == "UNKNOWN"

    def test_empty_string_behavior_safety_net(self):
        """Default "" is falsy AND distinct from "UNKNOWN". If someone
        changes the default to "UNKNOWN", the system would quietly treat
        all non-financial facts as "standard unknown" instead of
        "standard not applicable" — a silent semantic corruption.

        ""      → not applicable (crypto price, MVRV, macro indicator)
        "UNKNOWN" → data gap (should have a standard, couldn't determine)
        """
        f = Fact(id="f:0:1", kind="data", value=1.0, caliber="test")
        assert f.accounting_standard == "", (
            "accounting_standard default changed from ''! "
            "If intentional, you MUST update the three-state logic in "
            "derived_chain.py and all places that rely on '' meaning "
            "'not applicable' (not 'unknown')."
        )
        assert f.accounting_standard != "UNKNOWN", (
            "Default is NOT 'UNKNOWN' — 'not applicable' and 'unknown' "
            "are different states. If you want UNKNOWN as default, "
            "update the comment on line 24 of derived_chain.py."
        )


# ── Formula evaluation ────────────────────────────────────────

class TestFormulaEvaluation:
    """AST-safe formula evaluation: fact_ids, semantic refs, operators."""

    def test_simple_division(self):
        reg = FactRegistry(turn=0)
        _make_fact(reg, "revenue", 2.0e10, accounting_standard="US_GAAP")
        _make_fact(reg, "net_income", 5.0e8, accounting_standard="US_GAAP")
        output = "test\n[derivations]\nf:0:2 / f:0:1 = 0.025\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 1

    def test_yoy_formula_with_abs(self):
        reg = FactRegistry(turn=0)
        _make_fact(reg, "revenue", 2.2e10, period_end="2025-12-31")
        _make_fact(reg, "revenue", 1.6e10, period_end="2024-12-31")
        output = "test\n[derivations]\n(f:0:1 - f:0:2) / abs(f:0:2) = 0.375\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 1

    def test_semantic_refs(self):
        reg = FactRegistry(turn=0)
        _make_fact(reg, "revenue", 2.2e10, period_end="2025-12-31", period_type="quarter")
        _make_fact(reg, "revenue", 1.6e10, period_end="2024-12-31", period_type="quarter")
        output = "test\n[derivations]\n(revenue@2025Q4 - revenue@2024Q4) / abs(revenue@2024Q4) = 0.375\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 1

    def test_invalid_operator_rejected(self):
        reg = FactRegistry(turn=0)
        _make_fact(reg, "revenue", 2.0e10)
        _make_fact(reg, "revenue", 1.0e10)
        output = "test\n[derivations]\nf:0:1 ** 2 = 100\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.error_count >= 1

    def test_result_mismatch_rejected(self):
        reg = FactRegistry(turn=0)
        _make_fact(reg, "revenue", 2.0e10)
        _make_fact(reg, "revenue", 1.0e10)
        output = "test\n[derivations]\nf:0:1 / f:0:2 = 999.0\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.error_count >= 1

    def test_missing_parent_rejected(self):
        reg = FactRegistry(turn=0)
        _make_fact(reg, "revenue", 2.0e10)
        output = "test\n[derivations]\nf:99:99 / f:0:1 = 0.5\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.error_count >= 1


# ── Percentage bridge ─────────────────────────────────────────

class TestPercentageBridge:
    """Derived ratio values (0.382) must be matchable as percentages (38.2%) in output."""

    def test_ratio_gets_percentage_companion(self):
        reg = FactRegistry(turn=0)
        _make_fact(reg, "revenue", 2.2e10, period_end="2025-12-31", period_type="quarter")
        _make_fact(reg, "revenue", 1.6e10, period_end="2024-12-31", period_type="quarter")
        output = "test\n[derivations]\n(revenue@2025Q4 - revenue@2024Q4) / abs(revenue@2024Q4) = 0.375\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        register_derived_facts(dr, reg)
        # Should have 2 facts: the ratio (0.375) and the percentage companion (37.5)
        derived_facts = [f for f in reg.facts if f.kind == "derived"]
        assert len(derived_facts) >= 2, f"Expected ≥2 derived facts (ratio + % bridge), got {len(derived_facts)}"
        values = [f.value for f in derived_facts]
        # Ratio companion (0.375 ± small error)
        assert any(0.37 <= v <= 0.38 for v in values), f"Ratio companion missing in {values}"
        # Percentage bridge companion (37.5% → value ~37.5)
        pct_values = [v for v in values if v > 1]
        assert len(pct_values) >= 1, f"Percentage bridge companion missing in {values}"


# ── Precision inheritance ─────────────────────────────────────

class TestPrecisionInheritance:
    """2_sig_digits_from_billion parent → derived → display hint ≈X%."""

    def test_precision_inherits_from_parent(self):
        reg = FactRegistry(turn=0)
        _make_fact(reg, "net_income", 5.1e8, period_end="2025-12-31",
                   period_type="quarter", precision="2_sig_digits_from_billion")
        _make_fact(reg, "revenue", 2.225e10, period_end="2025-12-31",
                   period_type="quarter", precision="")
        output = "test\n[derivations]\nnet_income@2025Q4 / revenue@2025Q4 = 0.0229\n[/derivations]"
        dr = _parse_and_verify(output, reg)
        assert dr.verified_count == 1
        vd = dr.verified[0]
        assert vd.precision == "2_sig_digits_from_billion", (
            f"Precision should inherit 2_sig_digits, got {vd.precision!r}"
        )
        assert "≈" in vd.result_display_hint, (
            f"Display hint should show '≈', got {vd.result_display_hint!r}"
        )
