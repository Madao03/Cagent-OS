"""Criterion definitions — binary check items for each rubric dimension.

Each criterion is a yes/no question that an LLM judge can answer reliably.
This follows the "LLM as checklist executor, not final judge" pattern.

Phase 3e: Used by DeepEval runner to auto-evaluate agent responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Criterion:
    """A single binary check item."""
    id: str                # e.g. "facts_01"
    dimension: str         # task | facts | tools | reasoning | risk | format
    question: str          # yes/no question for LLM judge
    evidence_hint: str = ""  # what to look for in the response
    weight: float = 1.0    # relative weight within the dimension


# ── Six-dimension criterion catalog ──────────────────────────────────

DIMENSION_CRITERIA: dict[str, list[Criterion]] = {
    "task": [
        Criterion(
            id="task_01", dimension="task",
            question="Did the agent load the correct Skill(s) for the task?",
            evidence_hint="Check for Skill tool calls or skill references",
        ),
        Criterion(
            id="task_02", dimension="task",
            question="For financial instrument analysis: did the agent perform product structure decomposition (标的解构) before valuation?",
            evidence_hint="Look for [标的解构] tag, or explicit cash flow/pricing/control analysis",
        ),
        Criterion(
            id="task_03", dimension="task",
            question="Did the agent determine the appropriate time horizon before analysis?",
            evidence_hint="Especially important for macro analysis (short/medium/long)",
        ),
        Criterion(
            id="task_04", dimension="task",
            question="Did the agent search the local knowledge base (RAG) before external search?",
            evidence_hint="Check for financial.rag.search call",
        ),
    ],
    "facts": [
        Criterion(
            id="facts_01", dimension="facts",
            question="Are all numerical data points attributed to a specific source?",
            evidence_hint="Look for 'source:', 'from', 'according to', 'FRED', 'jin10'",
        ),
        Criterion(
            id="facts_02", dimension="facts",
            question="For L1 fast variables (price, holdings, cash, rates): are timestamps present?",
            evidence_hint="Look for dates like '2026-06-26', 'June 26', time labels",
        ),
        Criterion(
            id="facts_03", dimension="facts",
            question="Are there any numbers that appear to be from LLM training memory (no source)?",
            evidence_hint="Flag unsourced precise numbers — this is a NEGATIVE check",
        ),
        Criterion(
            id="facts_04", dimension="facts",
            question="For decision-critical numbers: are they cross-validated from at least two independent sources?",
            evidence_hint="Check for 'cross-validated', multiple source citations for same metric",
        ),
        Criterion(
            id="facts_05", dimension="facts",
            question="Are data sources appropriate for the data type (e.g., FRED for macro, CMC for crypto, not mixing)?",
            evidence_hint="Check tool choices match data domains",
        ),
    ],
    "tools": [
        Criterion(
            id="tools_01", dimension="tools",
            question="Did the agent prefer RAG (financial.rag.search) over external web search?",
            evidence_hint="Check if RAG was called before financial.websearch",
        ),
        Criterion(
            id="tools_02", dimension="tools",
            question="Did the agent use financial.quote.verified for cross-validation of valuation metrics?",
            evidence_hint="Check for quote.verified calls for PE/PB/ROE",
        ),
        Criterion(
            id="tools_03", dimension="tools",
            question="When a data source failed, did the agent follow the documented fallback chain instead of repeating the same call?",
            evidence_hint="Check error logs for retry patterns vs fallback patterns",
        ),
        Criterion(
            id="tools_04", dimension="tools",
            question="Were the correct tools used for the task type (not using web.search for structured finance data)?",
            evidence_hint="Check tool appropriateness for data domain",
        ),
    ],
    "reasoning": [
        Criterion(
            id="reasoning_01", dimension="reasoning",
            question="Is there a complete logical chain from data → analysis → conclusion (no causal gaps)?",
            evidence_hint="Look for 'A → B → C' chains, not 'A → C' jumps",
        ),
        Criterion(
            id="reasoning_02", dimension="reasoning",
            question="Are correlation and causation properly distinguished?",
            evidence_hint="Check for hedging language like 'correlated with', 'associated with' vs 'causes'",
        ),
        Criterion(
            id="reasoning_03", dimension="reasoning",
            question="Is the analysis grounded in the data actually retrieved (not general market knowledge)?",
            evidence_hint="Compare claims against retrieved data points",
        ),
        Criterion(
            id="reasoning_04", dimension="reasoning",
            question="Are opposing viewpoints or counter-arguments presented (not just the agent's own thesis)?",
            evidence_hint="Look for separate section with external opposing views",
        ),
    ],
    "risk": [
        Criterion(
            id="risk_01", dimension="risk",
            question="Does the output include a Red-Team challenge section identifying the strongest counter-argument?",
            evidence_hint="Look for '红方挑战', 'Red Team', or equivalent",
        ),
        Criterion(
            id="risk_02", dimension="risk",
            question="If probability/expected value is given: is the anchoring basis stated (historical frequency, market-implied, etc.)? If not applicable (pure data query): skip this criterion.",
            evidence_hint="Check for probability anchoring or ⚠️ subjective label",
        ),
        Criterion(
            id="risk_03", dimension="risk",
            question="Is confidence level explicitly stated for forward-looking conclusions?",
            evidence_hint="Look for 'confidence:', '置信度', or equivalent labels",
        ),
        Criterion(
            id="risk_04", dimension="risk",
            question="Are key risk factors and failure conditions identified?",
            evidence_hint="Look for 'what could go wrong', 'if X then thesis breaks'",
        ),
    ],
    "format": [
        Criterion(
            id="format_01", dimension="format",
            question="Is the output well-structured with clear section separation?",
            evidence_hint="Check for markdown headers, sections, logical flow",
        ),
        Criterion(
            id="format_02", dimension="format",
            question="Are data tables, when present, correctly formatted as markdown tables?",
            evidence_hint="Check for properly aligned | columns |",
        ),
        Criterion(
            id="format_03", dimension="format",
            question="Is the output concise or is there excessive verbosity/repetition?",
            evidence_hint="NEGATIVE check: flag if same point is made 3+ times",
        ),
        Criterion(
            id="format_04", dimension="format",
            question="Is the response appropriate for the inferred user expertise level (not over-explaining basics to a pro)?",
            evidence_hint="Check audience calibration per system rules",
        ),
    ],
}


def get_all_criteria() -> dict[str, list[Criterion]]:
    """Return the full criterion catalog organized by dimension."""
    return DIMENSION_CRITERIA


def get_criterion_by_id(cid: str) -> Criterion | None:
    """Look up a single criterion by ID."""
    for dim_criteria in DIMENSION_CRITERIA.values():
        for c in dim_criteria:
            if c.id == cid:
                return c
    return None


def dimension_to_score(
    results: dict[str, bool],  # criterion_id → pass/fail
    dimension: str,
) -> tuple[int, list[str]]:
    """Convert criterion results to a 0-4 dimension score.

    Returns (score, [evidence notes]).
    """
    dim_criteria = DIMENSION_CRITERIA.get(dimension, [])
    if not dim_criteria:
        return 0, []

    total = len(dim_criteria)
    passed = sum(1 for c in dim_criteria if results.get(c.id, False))

    # Map to 0-4 scale
    ratio = passed / total if total > 0 else 0
    if ratio >= 0.9: score = 4
    elif ratio >= 0.7: score = 3
    elif ratio >= 0.5: score = 2
    elif ratio >= 0.3:  score = 1
    else: score = 0

    notes = [f"{c.id}: {'PASS' if results.get(c.id, False) else 'FAIL'} — {c.question[:80]}" for c in dim_criteria]
    return score, notes


def total_score(results: dict[str, bool]) -> tuple[int, dict[str, int]]:
    """Calculate weighted total score (0-24) from criterion results."""
    weights = {
        "task": 20, "facts": 20, "tools": 15,
        "reasoning": 25, "risk": 10, "format": 10,
    }
    dim_scores = {}
    for dim in weights:
        score, _ = dimension_to_score(results, dim)
        dim_scores[dim] = score

    weighted = sum(score * weights[dim] / 100 * 6 for dim, score in dim_scores.items())
    return round(weighted), dim_scores
