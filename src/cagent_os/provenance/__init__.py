"""Provenance system — fact-level data溯源.

Makes data quality visible: every number in agent output is traceable
to a specific tool call, source, and caliber.
"""
from cagent_os.provenance.fact_registry import Fact, FactRegistry
from cagent_os.provenance.checker import check_provenance, annotate_output, CheckResult, TracedNumber
from cagent_os.provenance.gate import evaluate_gate, apply_markers, GateDecision
from cagent_os.provenance.derived_chain import (
    extract_derivations_block, verify_derivations, register_derived_facts,
    Derivation, VerifiedDerivation, DerivationResult,
)

__all__ = [
    "Fact", "FactRegistry",
    "check_provenance", "annotate_output", "CheckResult", "TracedNumber",
    "evaluate_gate", "apply_markers", "GateDecision",
    "extract_derivations_block", "verify_derivations", "register_derived_facts",
    "Derivation", "VerifiedDerivation", "DerivationResult",
]
