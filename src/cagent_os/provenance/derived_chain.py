"""P1 Derived Chain — agent declares derivation parents, checker verifies.

PROVENANCE_SYSTEM.md §3: derived numbers should be explicitly declared by
the agent with parent fact references, NOT reverse-searched from the registry.

Format (agent appends to output):
```
[derivations]
formula = result
[/derivations]
```

Where `formula` uses fact_ids (f:{turn}:{seq}) and operators: /, -, +, *, abs(), ().
Example:
```
[derivations]
f:0:21 / f:0:3 = 0.0229
(f:0:3 - f:0:16) / abs(f:0:16) = 0.382
[/derivations]
```

Inheritance rules (§3):
1. audited: min(parents) — derived from non-audited source → not audited
2. currency: mismatch between parents → reject derivation
3. precision: min(parents) — e.g., 2_sig_digits_from_billion parent
   → result can only claim 2 significant digits ("≈ 2.3%", not "2.2917%")
"""
from __future__ import annotations

import ast
import logging
import math as _math
import re
from dataclasses import dataclass, field
from typing import Any

from cagent_os.provenance.fact_registry import Fact, FactRegistry

logger = logging.getLogger(__name__)

# ── Block markers ───────────────────────────────────────────────

_DERIVATIONS_START = "[derivations]"
_DERIVATIONS_END = "[/derivations]"
_DERIVATIONS_BLOCK_RE = re.compile(
    r'\[derivations\]\s*\n(.*?)\n?\s*\[/derivations\]', re.DOTALL
)
_FACT_ID_RE = re.compile(r'f:\d+:\d+')
# Semantic reference: caliber@period (e.g., net_income@2025Q4, revenue@Q4 2025)
# Three supported period formats — avoids greedy regex that eats operators
_SEMANTIC_REF_RE = re.compile(
    r'([a-zA-Z_]\w*)@(FY\d{4}|\d{4}Q[1-4]|Q[1-4]\s+\d{4})',
    re.IGNORECASE,
)
_LINE_RE = re.compile(r'^(.+?)\s*=\s*(-?[\d.]+)\s*$')

# ── Period label ↔ period_end conversion ──────────────────────

def _period_to_query(label: str) -> tuple[str, str]:
    """Convert a period label back to (period_end, period_type).

    Examples:
        2025Q4 → ("2025-12-31", "quarter")
        Q4 2025 → ("2025-12-31", "quarter")
        FY2025 → ("2025-12-31", "fiscal_year")
        2024Q4 → ("2024-12-31", "quarter")
    """
    import re as _re
    label = label.strip()
    # FY2025 format
    m = _re.match(r'^FY(\d{4})$', label, _re.IGNORECASE)
    if m:
        year = int(m.group(1))
        return (f"{year}-12-31", "fiscal_year")
    # 2025Q4 format
    m = _re.match(r'^(\d{4})Q([1-4])$', label, _re.IGNORECASE)
    if m:
        year = int(m.group(1))
        q = int(m.group(2))
        month = q * 3
        return (f"{year}-{month:02d}-30" if month != 12 else f"{year}-12-31", "quarter")
    # Q4 2025 format (with space)
    m = _re.match(r'^Q([1-4])\s+(\d{4})$', label, _re.IGNORECASE)
    if m:
        q = int(m.group(1))
        year = int(m.group(2))
        month = q * 3
        return (f"{year}-{month:02d}-30" if month != 12 else f"{year}-12-31", "quarter")
    return ("", "")


def _find_fact_by_caliber_period(
    registry: FactRegistry, caliber: str, period_end: str, period_type: str,
) -> Fact | None:
    """Find a fact in registry by caliber + period_end + period_type.

    Used for semantic references like net_income@2025Q4.
    Matches case-insensitively on caliber.
    """
    caliber_lower = caliber.lower()
    for f in registry.facts:
        if f.kind not in ("data", "derived"):
            continue
        f_caliber = (getattr(f, 'caliber', '') or '').lower()
        f_period_end = getattr(f, 'period_end', '') or ''
        f_period_type = getattr(f, 'period_type', '') or ''
        if f_caliber == caliber_lower and f_period_end == period_end and f_period_type == period_type:
            return f
    return None

# ── Precision ranking ───────────────────────────────────────────
# Lower rank = fewer significant digits = lower precision.
# When inheriting, the derived fact gets the LOWEST (worst) precision
# of its parents.

_PRECISION_RANK: dict[str, int] = {
    "1_sig_digit_from_billion": 1,
    "2_sig_digits_from_billion": 2,
    "": 10,  # full precision — highest rank
}


def _precision_min(parents: list[Fact]) -> str:
    """Return the lowest-precision value among parents."""
    best_rank = 10
    best_precision = ""
    for p in parents:
        rank = _PRECISION_RANK.get(p.precision, 10)
        if rank < best_rank:
            best_rank = rank
            best_precision = p.precision
    return best_precision


def _precision_display_hint(precision: str, value: float) -> str:
    """Generate a display hint for the derived value based on precision.

    Example: 2_sig_digits_from_billion, value=0.022917 → "≈ 2.3%"
    """
    if not precision:
        return f"{value}"
    if "2_sig_digits" in precision:
        if abs(value) < 1:
            # ratio → percentage with 2 sig digits
            pct = value * 100
            return f"≈ {_to_sig_digits(pct, 2)}%"
        else:
            return f"≈ {_to_sig_digits(value, 2)}"
    if "1_sig_digit" in precision:
        if abs(value) < 1:
            pct = value * 100
            return f"≈ {_to_sig_digits(pct, 1)}%"
        else:
            return f"≈ {_to_sig_digits(value, 1)}"
    return f"{value}"


def _to_sig_digits(value: float, sig: int) -> str:
    """Format a float to N significant digits."""
    if value == 0:
        return "0"
    abs_val = abs(value)
    magnitude = int(_math.floor(_math.log10(abs_val)))
    # Round to (sig) digits
    factor = 10 ** (sig - 1 - magnitude)
    rounded = round(value * factor) / factor
    if abs(rounded) >= 10:
        # e.g., 10.0 → "10"
        return str(int(rounded))
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.{max(0, sig - 1 - magnitude)}f}"


# ── Data structures ─────────────────────────────────────────────

@dataclass
class Derivation:
    """A single parsed derivation from agent output."""
    line: str                    # raw line text
    formula: str                 # "f:0:21 / f:0:3" or "net_income@2025Q4 / revenue@2025Q4"
    parent_ids: list[str]        # ["f:0:21", "f:0:3"] — fact_id references
    claimed_result: float        # 0.0229
    parent_semantic: list[tuple[str, str]] = field(default_factory=list)
    # [("net_income", "2025Q4"), ("revenue", "2025Q4")] — semantic references
    _error: str = ""             # populated if verification fails

    @property
    def has_semantic_refs(self) -> bool:
        return len(self.parent_semantic) > 0

    @property
    def is_valid(self) -> bool:
        return not self._error

    @property
    def error(self) -> str:
        return self._error


@dataclass
class VerifiedDerivation:
    """A derivation that passed verification."""
    derivation: Derivation
    parent_facts: list[Fact]
    computed_value: float
    formula_display: str = ""           # "net_income / revenue"
    result_display_hint: str = ""       # "≈ 2.3%" (precision-aware)
    audited: bool | None = None
    currency: str = ""
    accounting_standard: str = ""       # inherited from parents — mismatch → reject
    precision: str = ""


@dataclass
class DerivationResult:
    """Result of parsing and verifying a derivations block."""
    derivations: list[Derivation] = field(default_factory=list)
    verified: list[VerifiedDerivation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # non-fatal flags (UNKNOWN std, etc.)
    block_text: str = ""           # the extracted block text
    block_start: int = -1          # position in output
    block_end: int = -1            # position in output

    @property
    def has_block(self) -> bool:
        return self.block_start >= 0

    @property
    def verified_count(self) -> int:
        return len(self.verified)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


# ── Parser ──────────────────────────────────────────────────────

def extract_derivations_block(output_text: str) -> tuple[str, DerivationResult | None]:
    """Extract and remove the [derivations] block from output text.

    Returns:
        (cleaned_text, DerivationResult or None if no block found)
    """
    match = _DERIVATIONS_BLOCK_RE.search(output_text)
    if not match:
        return output_text, None

    block_text = match.group(1)
    result = DerivationResult(
        block_text=block_text,
        block_start=match.start(),
        block_end=match.end(),
    )

    # Remove the block from output for normal provenance checking
    cleaned = output_text[:match.start()] + output_text[match.end():]

    # Parse each line
    for raw_line in block_text.strip().split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        derivation = _parse_derivation_line(line)
        if derivation:
            result.derivations.append(derivation)

    return cleaned, result


def _parse_derivation_line(line: str) -> Derivation | None:
    """Parse a single derivation line: 'formula = result'.

    Supports two reference formats:
      - fact_id:    f:0:3 / f:0:1 = 0.0229
      - semantic:   net_income@2025Q4 / revenue@2025Q4 = 0.0229
    Mixed format (f:0:3 / revenue@2025Q4) is also allowed.

    ★ Handles agent's inline calculations: splits on the FIRST '='
    for the formula and LAST '=' for the result, ignoring intermediate
    '=' signs that appear in inline annotations like
    "(222.54亿 - 161.05亿) / 161.05亿".
    """
    # Split: formula is before the FIRST '=', result is after the LAST '='
    if "=" not in line:
        return None
    parts = line.split("=")
    formula = parts[0].strip()
    result_str = parts[-1].strip()
    try:
        result_value = float(result_str)
    except ValueError:
        return None

    parent_ids = _FACT_ID_RE.findall(formula)
    semantic_matches = _SEMANTIC_REF_RE.findall(formula)
    parent_semantic = [(caliber, period) for caliber, period in semantic_matches]

    if not parent_ids and not parent_semantic:
        return None

    return Derivation(
        line=line,
        formula=formula,
        parent_ids=parent_ids,
        parent_semantic=parent_semantic,
        claimed_result=result_value,
    )


# ── Verifier ────────────────────────────────────────────────────

def verify_derivations(
    derivations: DerivationResult,
    registry: FactRegistry,
    tolerance: float = 0.02,
) -> DerivationResult:
    """Verify all parsed derivations against the fact registry.

    For each derivation:
    1. Look up all parent fact_ids in registry
    2. Check currency consistency
    3. Evaluate the formula with actual fact values
    4. Compare computed result with claimed result
    5. Apply inheritance rules (audited, currency, precision)

    Populates derivations.verified, derivations.errors, and derivations.warnings.
    """
    # Build lookup: fact_id → Fact
    fact_map: dict[str, Fact] = {}
    for f in registry.facts:
        fact_map[f.id] = f

    verified: list[VerifiedDerivation] = []
    errors: list[str] = []
    warnings: list[str] = []

    for d in derivations.derivations:
        # 1. Look up parents — support both fact_id and semantic references
        parents: list[Fact] = []
        missing: list[str] = []

        # Look up by fact_id
        for pid in d.parent_ids:
            fact = fact_map.get(pid)
            if fact is None:
                missing.append(pid)
            else:
                parents.append(fact)

        # Look up by caliber@period
        for caliber, period_label in d.parent_semantic:
            period_end, period_type = _period_to_query(period_label)
            if not period_end:
                missing.append(f"{caliber}@{period_label} (unknown period format)")
                continue
            # Find fact by caliber + period_end + period_type
            found = _find_fact_by_caliber_period(
                registry, caliber, period_end, period_type,
            )
            if found:
                parents.append(found)
                # Also add to fact_map under the semantic name for formula eval
                sem_key = f"{caliber}@{period_label}"
                fact_map[sem_key] = found
            else:
                missing.append(f"{caliber}@{period_label}")

        if missing:
            err = f"Missing parent facts: {missing} (derivation: {d.line})"
            errors.append(err)
            d._error = err
            continue

        # 2. Currency consistency
        currencies = {p.currency for p in parents if p.currency}
        if len(currencies) > 1:
            err = (
                f"Currency mismatch in derivation: {currencies} "
                f"(derivation: {d.line})"
            )
            errors.append(err)
            d._error = err
            continue

        # 2b. Accounting standard consistency — three-state semantics:
        #   "" (absent)   → not applicable (crypto/macro/market) → skip
        #   "UNKNOWN"     → should have one but data gap → flag, don't reject
        #   "CAS" / "US_GAAP" / "IFRS" → specific → participate in conflict
        #
        # ★ NOTE: "" ≠ UNKNOWN. "" means "this concept does not apply."
        #   UNKNOWN means "we know a standard exists but couldn't determine it."
        #   Conflating the two (as LANE 2 did before CIK lookup was added)
        #   makes the system unable to distinguish "market data" from "missing data."
        standards = {p.accounting_standard for p in parents if p.accounting_standard}
        known_standards = standards - {"UNKNOWN"}
        unknown_in_parents = "UNKNOWN" in standards

        if len(known_standards) > 1:
            err = (
                f"Accounting standard mismatch in derivation: {known_standards} "
                f"(derivation: {d.line})"
            )
            errors.append(err)
            d._error = err
            continue

        if unknown_in_parents:
            if len(known_standards) == 0:
                # All parents are UNKNOWN — flag but don't reject.
                # Same logic as LANE 2: "可能异常"用 flag，"逻辑不可能"才拒绝。
                warn = (
                    f"Accounting standard unknown for all parents "
                    f"(derivation: {d.line}). Derivation proceeds but "
                    f"standard cannot be verified."
                )
                warnings.append(warn)
            # Else: mixed (UNKNOWN + specific) — the specific value wins.
            # UNKNOWN doesn't contaminate the derivation; it just means
            # one parent's standard couldn't be determined. The known
            # standard from other parents is still valid for inheritance.

        # 3. Evaluate formula — replace semantic refs with fact_ids first
        eval_formula = d.formula
        for caliber, period_label in d.parent_semantic:
            sem_key = f"{caliber}@{period_label}"
            if sem_key in fact_map:
                eval_formula = eval_formula.replace(sem_key, fact_map[sem_key].id)

        try:
            computed = _evaluate_formula(eval_formula, parents)
        except Exception as exc:
            err = f"Formula evaluation failed: {exc} (derivation: {d.line})"
            errors.append(err)
            d._error = err
            continue

        # 4. Verify result
        if abs(computed) > 1e-12:
            rel_error = abs(d.claimed_result - computed) / abs(computed)
        else:
            rel_error = abs(d.claimed_result - computed)

        if rel_error > tolerance:
            err = (
                f"Result mismatch: claimed={d.claimed_result}, "
                f"computed={computed} (rel_err={rel_error:.3f}) "
                f"(derivation: {d.line})"
            )
            errors.append(err)
            d._error = err
            continue

        # 5. Inheritance rules
        # audited: min(parents) — None means unknown, treat as not audited
        audited_values = [p.audited for p in parents if p.audited is not None]
        derived_audited = all(audited_values) if audited_values else None

        # currency: all same (already checked above)
        derived_currency = next(iter(currencies), "")

        # accounting_standard: known value wins, UNKNOWN if all unknown, "" if all absent
        derived_standard = next(iter(known_standards), "UNKNOWN" if unknown_in_parents else "")

        # precision: min(parents)
        derived_precision = _precision_min(parents)

        # Build display formula
        formula_display = _build_display_formula(d.formula, parents)

        vd = VerifiedDerivation(
            derivation=d,
            parent_facts=parents,
            computed_value=computed,
            formula_display=formula_display,
            result_display_hint=_precision_display_hint(derived_precision, computed),
            audited=derived_audited,
            currency=derived_currency,
            accounting_standard=derived_standard,
            precision=derived_precision,
        )
        verified.append(vd)

    derivations.verified = verified
    derivations.errors = errors
    derivations.warnings = warnings
    return derivations


# ── Formula evaluator ───────────────────────────────────────────

def _evaluate_formula(formula: str, parents: list[Fact]) -> float:
    """Safely evaluate a derivation formula using parent fact values.

    References like 'f:0:3' (colons) and 'revenue@2025Q4' (@) are invalid
    in Python identifiers. We replace them with safe names first.
    Only allows: +, -, *, /, abs(), unary +/-, parentheses.
    """
    # Build value index: reference string → float
    value_index: dict[str, float] = {}
    for p in parents:
        try:
            v = float(p.value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Fact {p.id} value is not numeric: {p.value}") from exc
        value_index[p.id] = v

    # Replace all references (fact_id or semantic) with safe identifiers
    safe_formula = formula.strip()
    ref_to_safe: dict[str, str] = {}
    safe_value_map: dict[str, float] = {}

    # Find all references: fact_ids (f:\d+:\d+) and semantics (\w+@\w+)
    all_refs = _FACT_ID_RE.findall(safe_formula) + [
        f"{caliber}@{period}"
        for caliber, period in _SEMANTIC_REF_RE.findall(safe_formula)
    ]
    for ref in all_refs:
        if ref in ref_to_safe:
            continue
        safe_id = "__" + ref.replace(":", "_").replace("@", "_at_")
        ref_to_safe[ref] = safe_id
        safe_formula = safe_formula.replace(ref, safe_id)  # replace ALL occurrences

        # Look up value: try fact_id first, then semantic key
        if ref in value_index:
            safe_value_map[safe_id] = value_index[ref]
        else:
            raise ValueError(f"Reference '{ref}' not found in parent facts")

    # Parse the safe formula
    try:
        tree = ast.parse(safe_formula, mode='eval')
    except SyntaxError as exc:
        raise ValueError(f"Invalid formula syntax: {exc}") from exc

    # Transform: replace safe_id Name nodes with their numeric values
    transformed = _FormulaTransformer(safe_value_map).visit(tree)
    ast.fix_missing_locations(transformed)

    # Compile and evaluate the transformed Expression directly
    code = compile(transformed, '<derived>', 'eval')
    allowed_globals = {"abs": abs, "__builtins__": {}}
    result = eval(code, allowed_globals, {})

    if not isinstance(result, (int, float)):
        raise ValueError(f"Formula result is not a number: {type(result)}")
    return float(result)


class _FormulaTransformer(ast.NodeTransformer):
    """Replace fact_id Name nodes with their numeric Constant values."""

    def __init__(self, value_map: dict[str, float]) -> None:
        self._value_map = value_map
        self._allowed_functions = {"abs"}

    def visit_Name(self, node: ast.Name) -> ast.AST:
        """Replace fact_id names with numeric constants.

        Skips function names ('abs') which are handled by visit_Call.
        """
        if node.id in self._allowed_functions:
            return node  # leave function names intact
        if node.id in self._value_map:
            return ast.Constant(value=self._value_map[node.id])
        raise ValueError(f"Unknown name in formula (not a fact_id): {node.id}")

    def visit_Call(self, node: ast.Call) -> ast.AST:
        """Allow only abs() calls."""
        if isinstance(node.func, ast.Name):
            if node.func.id not in self._allowed_functions:
                raise ValueError(
                    f"Function not allowed: {node.func.id}. "
                    f"Only: {self._allowed_functions}"
                )
        return self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        """Allow only +, -, *, / operators."""
        allowed_ops = (ast.Add, ast.Sub, ast.Mult, ast.Div)
        if not isinstance(node.op, allowed_ops):
            raise ValueError(
                f"Operator not allowed: {type(node.op).__name__}. "
                f"Only: +, -, *, /"
            )
        return self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        """Allow only +, - unary operators."""
        allowed = (ast.UAdd, ast.USub)
        if not isinstance(node.op, allowed):
            raise ValueError(
                f"Unary operator not allowed: {type(node.op).__name__}"
            )
        return self.generic_visit(node)


# ── Display helpers ─────────────────────────────────────────────

def _build_display_formula(formula: str, parents: list[Fact]) -> str:
    """Build a human-readable formula string using caliber names."""
    id_to_label: dict[str, str] = {}
    for p in parents:
        label = p.caliber or p.display or p.id
        id_to_label[p.id] = label

    result = formula
    for fid, label in id_to_label.items():
        result = result.replace(fid, label)
    return result


def format_derived_fact_display(vd: VerifiedDerivation) -> str:
    """Generate a display string for a verified derived fact.

    Example: "净利率 = net_income / revenue = 0.0229 (≈ 2.3%)"
    """
    return (
        f"{vd.formula_display} = {vd.derivation.claimed_result}"
        f"{' (' + vd.result_display_hint + ')' if vd.result_display_hint else ''}"
    )


# ── Registry integration ────────────────────────────────────────

def register_derived_facts(
    derivations: DerivationResult,
    registry: FactRegistry,
) -> list[Fact]:
    """Register verified derivations as derived-kind facts in the registry.

    Each verified derivation becomes a Fact with:
      - kind = "derived"
      - source = aggregated from parents
      - audited, currency, precision = inherited
      - display = human-readable formula + result

    ★ Percentage bridge: if the derived value is a small ratio (|v| < 1),
    a companion fact with ×100 scaling is also registered. This allows
    the checker to match both "0.3817" (ratio) and "38.2%" (percentage)
    in agent output — agents naturally write percentages, not raw ratios.
    """
    registered: list[Fact] = []
    for vd in derivations.verified:
        parents = vd.parent_facts
        source = "+".join(sorted(set(p.source for p in parents if p.source)))
        parent_ids_str = ",".join(sorted(vd.derivation.parent_ids))

        fact = Fact(
            id=registry.next_id(),
            kind="derived",
            value=vd.computed_value,
            display=format_derived_fact_display(vd),
            source=source,
            capability="provenance.derived",
            audited=vd.audited,
            currency=vd.currency,
            accounting_standard=vd.accounting_standard,
            precision=vd.precision,
            caliber=f"derived({parent_ids_str})",
            confidence="medium",
        )
        registry._facts.append(fact)
        registered.append(fact)

        # ★ Percentage bridge: register ×100 companion for ratio values.
        # Agent output typically writes "同比增长 38.2%" (value=38.2) not
        # "ratio 0.382". Without this companion, derived facts never match
        # the percentage-display numbers in the output text.
        if 0 < abs(vd.computed_value) < 1:
            pct_value = vd.computed_value * 100
            pct_fact = Fact(
                id=registry.next_id(),
                kind="derived",
                value=pct_value,
                display=format_derived_fact_display(vd) + f" ({pct_value:.1f}%)",
                source=source,
                capability="provenance.derived",
                audited=vd.audited,
                currency=vd.currency,
                accounting_standard=vd.accounting_standard,
                precision=vd.precision,
                caliber=f"derived({parent_ids_str})",
                confidence="medium",
            )
            registry._facts.append(pct_fact)
            registered.append(pct_fact)

    return registered
