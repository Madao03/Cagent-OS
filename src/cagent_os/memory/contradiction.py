"""LLM-powered contradiction detection.

Phase 2d: Compares new analysis conclusions against historical investment
theses to find contradictions. When a contradiction is detected, it is
logged to the contradiction_log table and surfaced to the user.

How it works:
  1. After each analysis run, extract ticker-related claims
  2. For each claim, query memory for existing theses on that ticker
  3. Use a small, focused LLM call to check: "does new X contradict old Y?"
  4. If yes → log contradiction, notify user

Design: lightweight wrapper around the MemoryAPI. Does NOT require
vector search — uses simple keyword + ticker matching. Phase 3+ can
upgrade to embedding-based semantic search.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cagent_os.memory.api import ContradictionLog, InvestmentThesis, MemoryAPI, UserFact

logger = logging.getLogger(__name__)


@dataclass
class Claim:
    """A single claim extracted from an analysis output."""
    ticker: str
    statement: str      # the factual claim (e.g. "NVDA forward PE is 25")
    direction: str = ""  # "bullish" | "bearish" | "neutral"
    confidence: str = "medium"


@dataclass
class ContradictionResult:
    """Result of a contradiction check between two claims."""
    claim_a: str
    claim_b: str
    is_contradiction: bool
    explanation: str = ""


class ContradictionDetector:
    """Detect contradictions between new claims and historical theses.

    Uses an LLM backend for semantic comparison. This is intentionally
    simple — a focused prompt, not a full agent.
    """

    # Prompt template for contradiction detection
    DETECT_PROMPT = """You are a financial fact-checker. Compare two statements about the same asset and determine if they CONTRADICT each other.

A contradiction means: if statement A is true, statement B CANNOT be true at the same time (about the same time period).

Examples of contradictions:
  - A: "NVDA PE is 25, undervalued" vs B: "NVDA PE is 35, overvalued" → CONTRADICT (different PE assessment)
  - A: "BTC bull market" vs B: "BTC bear market starting" → CONTRADICT (opposite direction)
  - A: "Fed will cut rates in Q3" vs B: "Fed will hike in Q3" → CONTRADICT (opposite policy)

Examples of NON-contradictions:
  - A: "NVDA PE 25" vs B: "NVDA PE 26" → NOT contradiction (minor numerical difference)
  - A: "BTC short-term bullish" vs B: "BTC long-term bearish" → NOT contradiction (different time frames)
  - A: "NVDA revenue growing" vs B: "NVDA margins shrinking" → NOT contradiction (different metrics)

Old statement: {old_statement}
New statement: {new_statement}

Respond in JSON: {{"is_contradiction": true/false, "explanation": "one sentence explaining why"}}"""

    def __init__(self, llm_backend=None) -> None:
        """llm_backend: any object with a complete() or generate() method."""
        self._llm = llm_backend

    def extract_claims(self, analysis_output: str, tickers: list[str]) -> list[Claim]:
        """Extract ticker-related claims from an analysis output."""
        claims: list[Claim] = []
        if not analysis_output or not tickers:
            return claims

        analysis_lower = analysis_output.lower()
        for ticker in tickers:
            ticker_upper = ticker.upper()
            # Find sentences mentioning this ticker
            import re
            sentences = re.split(r'(?<=[.!?])\s+', analysis_output)
            for sent in sentences:
                if ticker_upper in sent.upper() and len(sent) > 20:
                    direction = "neutral"
                    bull_words = ["bullish", "undervalued", "buy", "accumulate", "outperform", "upside", "growth"]
                    bear_words = ["bearish", "overvalued", "sell", "reduce", "underperform", "downside", "decline"]
                    sent_lower = sent.lower()
                    if any(w in sent_lower for w in bull_words):
                        direction = "bullish"
                    elif any(w in sent_lower for w in bear_words):
                        direction = "bearish"
                    claims.append(Claim(ticker=ticker_upper, statement=sent.strip(), direction=direction))
        return claims

    async def check(
        self,
        memory: MemoryAPI,
        user_id: str,
        analysis_output: str,
        tickers: list[str],
    ) -> list[ContradictionLog]:
        """Check a new analysis output against stored theses for contradictions.

        Returns list of newly detected contradictions (already saved to memory).
        """
        if not self._llm:
            logger.warning("ContradictionDetector: no LLM backend, skipping check")
            return []

        claims = self.extract_claims(analysis_output, tickers)
        if not claims:
            return []

        contradictions: list[ContradictionLog] = []

        for claim in claims:
            # Query existing theses for this ticker
            existing = await memory.query_by_ticker(user_id, claim.ticker)
            if not existing:
                continue

            for thesis in existing:
                # Skip if thesis content is too short
                if len(thesis.content) < 20:
                    continue

                # Use LLM to check contradiction
                try:
                    prompt = self.DETECT_PROMPT.format(
                        old_statement=thesis.content[:500],
                        new_statement=claim.statement[:500],
                    )
                    response = await self._call_llm(prompt)
                    result = self._parse_response(response)

                    if result and result.is_contradiction:
                        log_entry = ContradictionLog(
                            user_id=user_id,
                            ticker=claim.ticker,
                            old_fact=thesis.content[:300],
                            new_fact=claim.statement[:300],
                            detected_at=datetime.now(timezone.utc),
                            resolved=False,
                        )
                        await memory.save_contradiction(log_entry)
                        contradictions.append(log_entry)
                        logger.info(
                            "Contradiction detected: %s — old=%s... new=%s...",
                            claim.ticker,
                            thesis.content[:80],
                            claim.statement[:80],
                        )
                except Exception as exc:
                    logger.warning("Contradiction check failed for %s: %s", claim.ticker, exc)
                    continue

        return contradictions

    async def _call_llm(self, prompt: str) -> str:
        """Call the LLM backend and return text response."""
        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.0,
            )
            if hasattr(response, 'content'):
                return response.content
            if isinstance(response, dict):
                return response.get("content", "")
            return str(response)
        except Exception as exc:
            logger.warning("LLM call failed for contradiction detection: %s", exc)
            return ""

    @staticmethod
    def _parse_response(text: str) -> ContradictionResult | None:
        """Parse the LLM's JSON response."""
        if not text:
            return None
        try:
            # Extract JSON from response (may have markdown wrapping)
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
            data = json.loads(text)
            return ContradictionResult(
                claim_a="",
                claim_b="",
                is_contradiction=data.get("is_contradiction", False),
                explanation=data.get("explanation", ""),
            )
        except (json.JSONDecodeError, KeyError):
            return None


# ── Convenience: run contradiction check against stored facts ──────

async def check_analysis_against_memory(
    memory: MemoryAPI,
    llm_backend,
    user_id: str,
    analysis_output: str,
    tickers: list[str],
) -> list[ContradictionLog]:
    """One-shot: check an analysis for contradictions and log any found.

    Returns the list of newly detected contradictions (empty = no issues).
    """
    detector = ContradictionDetector(llm_backend=llm_backend)
    return await detector.check(
        memory=memory,
        user_id=user_id,
        analysis_output=analysis_output,
        tickers=tickers,
    )
