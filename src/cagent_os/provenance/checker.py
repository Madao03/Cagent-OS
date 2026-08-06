"""Provenance checker — validates that all numbers in agent output are traced.

Scans agent output text, extracts all data-like numbers, and checks them
against the FactRegistry. Untraced numbers are flagged (not removed).

This is the "无溯源不输出" enforcement layer (PROVENANCE_SYSTEM.md §4).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from cagent_os.provenance.fact_registry import Fact, FactRegistry
from cagent_os.provenance.normalizer import extract_numbers, ExtractedNumber
from cagent_os.provenance.derived_chain import (
    extract_derivations_block, verify_derivations, register_derived_facts,
    VerifiedDerivation, DerivationResult,
)

logger = logging.getLogger(__name__)

# Sentence boundary characters — when scanning backward from a number,
# we stop at these to get the clause that modifies the number.
#
# Sign keywords AFTER the number ("¥578.6亿的亏损") are NOT detected.
# This is INTENTIONAL and fails SAFE:
#   keyword after → not detected → abs matching not triggered
#   → number stays untraced (visible false positive, fixable)
#   NOT: → incorrectly traced with wrong sign (hidden false negative, dangerous)
#
# This is safe because Chinese financial convention puts labels BEFORE numbers.
_CLAUSE_BOUNDARIES = set("，。；；、：\n\r。！？;,")

# Sentence boundaries for original sentence extraction in verbatim citation.
# More restrictive than clause boundaries: only true sentence-ending punctuation.
_SENTENCE_BOUNDARIES = set("。！？\n\r.!")


def _extract_preceding_clause(text: str, position: int) -> str:
    """Extract the text from the nearest clause boundary to `position`.

    Args:
        position: the START index of the number match (match.start()).

    Scans backward from `position` until hitting a punctuation mark or
    the start of the text. Returns the preceding clause (the modifier
    for the number at `position`).

    This is stable across different text layouts — unlike a fixed char
    window, it adapts to actual sentence structure.
    """
    start = position
    while start > 0 and text[start - 1] not in _CLAUSE_BOUNDARIES:
        start -= 1
    return text[start:position]


@dataclass
class TracedNumber:
    """A number found in agent output, with its provenance status."""
    raw: str               # original text: "¥767.2亿"
    value: float           # normalized: 76720000000.0
    start: int             # position in output text
    end: int               # position in output text
    status: str            # "traced" | "untraced" | "non_data" | "sign_conflict"
    kind: str = ""         # "data" | "verified_citation" — how it was traced
    fact_id: str = ""      # matched fact ID (if traced or sign_conflict)
    source: str = ""       # matched fact source (if traced or sign_conflict)
    conflict_detail: str = ""  # human-readable conflict description (if sign_conflict)
    citation_url: str = ""     # URL of source (if verified_citation)
    citation_sentence: str = ""  # original sentence from source (if verified_citation)
    variant_used: str = ""   # which search variant matched (for audit)


@dataclass
class CheckResult:
    """Result of provenance check on agent output."""
    total_numbers: int = 0
    traced: int = 0
    untraced: int = 0
    non_data: int = 0
    sign_conflicts: int = 0
    verified_citation: int = 0  # traced via verbatim match in text sources
    # P1 derived chain
    derived_traced: int = 0     # traced via explicit derivation declaration
    derived_errors: list[str] = field(default_factory=list)
    derived_warnings: list[str] = field(default_factory=list)  # non-fatal flags
    derivations: list[dict] = field(default_factory=list)  # serialized for frontend
    derivation_result: DerivationResult | None = None
    untraced_numbers: list[TracedNumber] = field(default_factory=list)
    sign_conflict_numbers: list[TracedNumber] = field(default_factory=list)
    traced_numbers: list[TracedNumber] = field(default_factory=list)

    @property
    def untraced_rate(self) -> float:
        """未溯源数字率 = untraced / (traced + untraced). Non-data excluded."""
        denom = self.traced + self.untraced
        if denom == 0:
            return 0.0
        return self.untraced / denom

    @property
    def coverage_rate(self) -> float:
        """溯源覆盖率 = traced / (traced + untraced)."""
        denom = self.traced + self.untraced
        if denom == 0:
            return 1.0
        return self.traced / denom

    def summary(self) -> str:
        cit_part = f", {self.verified_citation} verbatim" if self.verified_citation else ""
        der_part = f", {self.derived_traced} derived" if self.derived_traced else ""
        total_traced = self.traced + self.derived_traced
        total_untraced = self.untraced
        denom = total_traced + total_untraced
        cov = total_traced / denom if denom > 0 else 1.0
        return (
            f"Provenance: {total_traced}/{total_traced + total_untraced} traced "
            f"({cov:.0%} coverage){cit_part}{der_part}, "
            f"{total_untraced} untraced, "
            f"{self.non_data} non-data excluded"
        )


def _make_search_variants(raw: str) -> list[str]:
    """Generate search variants for verbatim matching.

    Verbatim matching boundary (PRINCIPLE):
      ✅ ALLOWED (pure surface-format differences, same literal value):
         - Currency symbols: ¥767.2亿 → 767.2亿
         - Thousands commas: 1,977亿 → 1977亿, 1977亿 → 1,977亿
         - Full/half-width: ．→ .  （→ ( ）→ )
         - Whitespace: "1,234 亿" → "1,234亿"

      ❌ FORBIDDEN (requires computation, not verbatim):
         - Unit conversion: "RMB 76.72 billion" ≠ "¥767.2亿" (×10 conversion)
         - Magnitude conversion: "767亿" ≠ "7670亿" (×10)
         - Rounding: "767.2亿" ≠ "767亿" (precision loss)
         - Exchange rate: "$10B" ≠ "¥72B"

    Cross-unit matches are DERIVED, not traced — they represent a computation
    step and should go through the derivation chain, not bypass the gate.

    Handles common formatting differences between agent output and source text.
    """
    _CURRENCY_SYMBOLS = "¥￥$"
    variants = [raw]
    # Strip currency prefix
    stripped = raw.lstrip(_CURRENCY_SYMBOLS)
    if stripped != raw:
        variants.append(stripped)
    # Strip commas
    no_comma = raw.replace(",", "")
    if no_comma != raw:
        variants.append(no_comma)
    # Strip both currency and commas
    no_comma_stripped = stripped.replace(",", "")
    if no_comma_stripped != stripped and no_comma_stripped != no_comma:
        variants.append(no_comma_stripped)
    # Insert thousands comma (for sources that use commas when agent doesn't)
    # e.g., agent "1977亿" should match source "1,977亿美元"
    _comma_var = _insert_thousands_comma(no_comma)
    if _comma_var and _comma_var != no_comma:
        # Also try currency-stripped version of comma variant
        _comma_stripped = _comma_var.lstrip(_CURRENCY_SYMBOLS)
        if _comma_stripped != _comma_var:
            variants.append(_comma_stripped)
        variants.append(_comma_var)

    # ★ Western magnitude suffix variants: billion↔B, million↔M, trillion↔T
    # These are pure surface-format differences (same literal value), not
    # unit conversions. "billion" and "B" both mean ×10^9.
    import re as _re
    _MAGNITUDE_MAP = {
        "trillion": "T", "billion": "B", "million": "M",
        "bn": "B", "bn.": "B",
        "tn": "T", "tn.": "T",
        "mn": "M", "mn.": "M",
    }
    _REVERSE_MAP = {v: k for k, v in _MAGNITUDE_MAP.items()}
    # Also map full words to short forms
    _MAGNITUDE_MAP["trillion"] = "T"
    for full, short in [("billion", "B"), ("trillion", "T"), ("million", "M")]:
        if full in raw.lower():
            for v in list(variants):
                replaced = _re.sub(_re.escape(full), short, v, flags=_re.IGNORECASE)
                if replaced != v:
                    variants.append(replaced)
        if short in raw and raw.upper() != raw.replace(short, ""):
            for v in list(variants):
                replaced = _re.sub(_re.escape(short), full, v, flags=_re.IGNORECASE)
                if replaced != v:
                    variants.append(replaced)
    # Also handle bn/tn/mn short forms
    for short_full in [("bn", "billion"), ("tn", "trillion"), ("mn", "million")]:
        short, full = short_full
        pattern = _re.compile(r'\b' + _re.escape(short) + r'\b', _re.IGNORECASE)
        if pattern.search(raw):
            for v in list(variants):
                replaced = pattern.sub(full, v)
                if replaced != v:
                    variants.append(replaced)

    # Deduplicate preserving order
    seen = set(); unique = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def _insert_thousands_comma(raw: str) -> str | None:
    """Insert thousands comma into digit portion of a raw number string.

    Examples:
        "1977亿" -> "1,977亿"
        "16720000000" -> "16,720,000,000"
        "767.2亿" -> None (decimal, no comma insertion)
    """
    import re as _re
    # Match: digits (no commas) possibly followed by magnitude/unit
    m = _re.match(r'^(\d{4,})(\.\d+)?(.*)$', raw)
    if not m:
        return None
    digits, decimal, suffix = m.groups()
    # Insert commas every 3 digits from the right
    result = []
    for i, ch in enumerate(reversed(digits)):
        if i > 0 and i % 3 == 0:
            result.append(',')
        result.append(ch)
    formatted = ''.join(reversed(result))
    return formatted + (decimal or '') + (suffix or '')


def _extract_surrounding_sentence(text: str, match_start: int, match_len: int) -> str:
    """Extract the original sentence containing a verbatim match.

    Expands from the match position to the nearest sentence boundaries
    (。！？\\n), capped at 200 chars each direction.
    """
    match_end = match_start + match_len

    # Backward to sentence start (up to 200 chars)
    start = match_start
    limit = max(0, match_start - 200)
    while start > limit and text[start - 1] not in _SENTENCE_BOUNDARIES:
        start -= 1

    # Forward to sentence end (up to 200 chars)
    end = match_end
    limit = min(len(text), match_end + 200)
    while end < limit and text[end] not in _SENTENCE_BOUNDARIES:
        end += 1
    if end < len(text) and text[end] in _SENTENCE_BOUNDARIES:
        end += 1  # include the boundary punctuation

    return text[start:end].strip()


def _check_verbatim_citation(
    num: ExtractedNumber,
    registry: FactRegistry,
) -> dict | None:
    """Check if a number appears verbatim in any verified_citation source text.

    Iterates all verified_citation facts (text containers from web/PANews/RAG
    results) and searches for the number's raw text in each. If found verbatim,
    returns the fact metadata, the original sentence containing the match,
    and which variant matched (for auditability).

    Returns:
        dict with fact_id, source, url, sentence, variant — or None if not found.
    """
    for fact in registry.facts:
        if fact.kind != "verified_citation":
            continue
        text = str(fact.value) if fact.value else ""
        if not text:
            continue

        for variant in _make_search_variants(num.raw):
            idx = text.find(variant)
            if idx == -1:
                continue

            sentence = _extract_surrounding_sentence(text, idx, len(variant))
            return {
                "fact_id": fact.id,
                "source": fact.source,
                "url": fact.url,
                "sentence": sentence,
                "variant": variant if variant != num.raw else "",
            }

    return None


def check_provenance(
    output_text: str,
    registry: FactRegistry,
    tolerance: float = 0.005,
) -> CheckResult:
    """Check all numbers in agent output against the fact registry.

    Args:
        output_text: the agent's final output text
        registry: per-turn FactRegistry with all tool-returned facts
        tolerance: relative tolerance for value matching (0.5% by default)

    Returns:
        CheckResult with traced/untraced breakdown and positions.
    """
    # ── P1: Extract and verify derivation block ──
    # Parse [derivations]...[/derivations] before normal number extraction.
    # The derivation block is removed from the output text so its numbers
    # don't get extracted and checked as regular data.
    cleaned_text, derivation_result = extract_derivations_block(output_text)
    result = CheckResult(
        derivation_result=derivation_result,
    )
    if derivation_result and derivation_result.derivations:
        verify_derivations(derivation_result, registry)
        register_derived_facts(derivation_result, registry)
        result.derived_traced = derivation_result.verified_count
        result.derived_errors = derivation_result.errors
        result.derived_warnings = derivation_result.warnings
        # ★ Serialize verified derivations for frontend derived expansion
        for vd in derivation_result.verified:
            parent_ids_str = ",".join(sorted(vd.derivation.parent_ids))
            # Find the matching fact_id(s) in registry — derived facts are registered
            # with caliber="derived(parent_ids)". Match by parent_ids to find fact_id.
            for fact in registry.facts:
                if fact.kind == "derived" and parent_ids_str in fact.caliber:
                    result.derivations.append({
                        "fact_id": fact.id,
                        "formula_display": vd.formula_display,
                        "result_display_hint": vd.result_display_hint,
                        "parent_ids": sorted(vd.derivation.parent_ids),
                        "computed_value": vd.computed_value,
                    })
                    break  # one fact_id per derivation
        logger.debug(
            "Derived chain: %d verified, %d errors, %d warnings",
            derivation_result.verified_count,
            derivation_result.error_count,
            derivation_result.warning_count,
        )

    # ── Normal provenance check on cleaned text ──
    numbers = extract_numbers(cleaned_text)
    result.total_numbers = len(numbers)

    # Keywords for sign conflict detection
    LOSS_KEYWORDS = {"亏损", "损失", "下降", "减少", "负", "净亏",
                     "loss", "decrease", "decline", "negative", "drop"}
    GAIN_KEYWORDS = {"利润", "盈利", "增长", "增加", "正", "净利",
                     "profit", "gain", "increase", "growth", "positive"}

    for num in numbers:
        if not num.is_data:
            result.non_data += 1
            continue

        # Extract sign context by sentence boundary, not fixed char count.
        # Chinese sign keywords are ALWAYS before the number ("净亏损 ¥578.6亿").
        # Looking forward after the number bleeds into the next clause.
        # Solution: scan backward from number start to nearest punctuation,
        # don't look forward at all.
        context_window = _extract_preceding_clause(cleaned_text, num.start)
        context_has_gain = any(kw in context_window for kw in GAIN_KEYWORDS)
        context_has_loss = any(kw in context_window for kw in LOSS_KEYWORDS)

        # Pass 1: normal match (exact value + loss-context abs matching)
        match = registry.find_by_value(
            num.value, tolerance=tolerance, sign_context=context_window,
        )

        # Pass 2: if no normal match, try force_abs to detect sign conflict
        # (Registry negative + output positive with "profit" context = danger)
        if not match:
            match = registry.find_by_value(
                num.value, tolerance=tolerance, force_abs=True,
            )
            if match:
                # ★ This matched only on absolute value → potential sign conflict
                try:
                    fact_val = float(match.value)
                except (ValueError, TypeError):
                    fact_val = 0

                # Registry negative + output says "profit/growth"
                if fact_val < 0 and num.value > 0 and context_has_gain and not context_has_loss:
                    result.sign_conflicts += 1
                    result.sign_conflict_numbers.append(TracedNumber(
                        raw=num.raw, value=num.value,
                        start=num.start, end=num.end,
                        status="sign_conflict",
                        fact_id=match.id,
                        source=match.source,
                        conflict_detail=(
                            f"Registry value {fact_val} is negative (loss/decline), "
                            f"but output context says 'profit/growth'. "
                            f"Possible sign error in agent output."
                        ),
                    ))
                    continue

                # Registry positive + output says "loss/decline"
                if fact_val > 0 and num.value > 0 and context_has_loss and not context_has_gain:
                    result.sign_conflicts += 1
                    result.sign_conflict_numbers.append(TracedNumber(
                        raw=num.raw, value=num.value,
                        start=num.start, end=num.end,
                        status="sign_conflict",
                        fact_id=match.id,
                        source=match.source,
                        conflict_detail=(
                            f"Registry value {fact_val} is positive (profit/gain), "
                            f"but output context says 'loss/decline'. "
                            f"Possible sign error in agent output."
                        ),
                    ))
                    continue

        if match:
            try:
                fact_val = float(match.value)
            except (ValueError, TypeError):
                fact_val = 0

            context_has_gain = any(kw in context_window for kw in GAIN_KEYWORDS)
            context_has_loss = any(kw in context_window for kw in LOSS_KEYWORDS)

            # Registry negative + output says "profit" = SIGN CONFLICT
            if fact_val < 0 and num.value > 0 and context_has_gain and not context_has_loss:
                result.sign_conflicts += 1
                result.sign_conflict_numbers.append(TracedNumber(
                    raw=num.raw, value=num.value,
                    start=num.start, end=num.end,
                    status="sign_conflict",
                    fact_id=match.id,
                    source=match.source,
                    conflict_detail=(
                        f"Registry value {fact_val} is negative (loss/decline), "
                        f"but output context says 'profit/growth'. "
                        f"Possible sign error in agent output."
                    ),
                ))
                continue

            # Registry positive + output says "loss" = SIGN CONFLICT
            if fact_val > 0 and num.value > 0 and context_has_loss and not context_has_gain:
                result.sign_conflicts += 1
                result.sign_conflict_numbers.append(TracedNumber(
                    raw=num.raw, value=num.value,
                    start=num.start, end=num.end,
                    status="sign_conflict",
                    fact_id=match.id,
                    source=match.source,
                    conflict_detail=(
                        f"Registry value {fact_val} is positive (profit/gain), "
                        f"but output context says 'loss/decline'. "
                        f"Possible sign error in agent output."
                    ),
                ))
                continue

            result.traced += 1
            result.traced_numbers.append(TracedNumber(
                raw=num.raw, value=num.value,
                start=num.start, end=num.end,
                status="traced",
                fact_id=match.id,
                source=match.source,
            ))
        else:
            # Pass 3: verbatim check against verified_citation text sources.
            # A number is only traced from text sources if it appears verbatim
            # in the actual tool-returned content — not just claimed to be
            # from a URL (prevents motivated citation).
            cit = _check_verbatim_citation(num, registry)
            if cit:
                result.verified_citation += 1
                result.traced += 1
                result.traced_numbers.append(TracedNumber(
                    raw=num.raw, value=num.value,
                    start=num.start, end=num.end,
                    status="traced",
                    kind="verified_citation",
                    fact_id=cit["fact_id"],
                    source=cit["source"],
                    citation_url=cit["url"],
                    citation_sentence=cit["sentence"],
                    variant_used=cit.get("variant", ""),
                ))
            else:
                result.untraced += 1
                result.untraced_numbers.append(TracedNumber(
                    raw=num.raw, value=num.value,
                    start=num.start, end=num.end,
                    status="untraced",
                ))

    return result


def annotate_output(
    output_text: str,
    result: CheckResult,
    mode: str = "production",
) -> str:
    """Annotate output text with provenance markers.

    In production mode: untraced numbers get a visible ⚠️ marker.
    In dev/eval mode: untraced numbers get a hard [UNTRACED] tag.

    Does NOT remove untraced numbers — makes them visible (PROVENANCE_SYSTEM.md §4).
    """
    if not result.untraced_numbers:
        return output_text

    # Work backwards (positions stay valid)
    annotated = output_text
    for num in sorted(result.untraced_numbers, key=lambda n: n.start, reverse=True):
        marker = "⚠️" if mode == "production" else "[UNTRACED]"
        annotated = (
            annotated[:num.end]
            + f" {marker}"
            + annotated[num.end:]
        )

    return annotated
