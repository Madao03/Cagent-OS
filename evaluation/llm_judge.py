"""LLM Judge — criterion-by-criterion evaluation of agent responses.

Uses DeepSeek (same provider as the agent) to judge each criterion independently.
Follows the "LLM as checklist executor, not final judge" pattern.

Phase 3e: Core evaluation engine. Phase 3f: Dashboard integration.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Load .env for API key
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# DeepSeek API config
_DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
_DEEPSEEK_MODEL = "deepseek-chat"  # cheaper than v4-pro for eval tasks

_JUDGE_PROMPT = """You are an evaluation judge for a financial research AI agent. Your task is to check ONE specific criterion against the agent's response.

## Criterion to Check
[{dim_upper}] {question}
Hint: {evidence_hint}

## User Question
{query}

## Agent Response
{response}

## Instructions
1. Read the criterion carefully. It is a YES/NO question.
2. Check if the agent's response SATISFIES this criterion.
3. You MUST answer with ONLY this JSON format (no other text):
{{"satisfied": true/false, "evidence": "Short quote from response that proves your judgment (or reason for fail)"}}

IMPORTANT: Output ONLY the JSON. Do not add explanations or markdown fences."""


class LLMJudge:
    """Evaluates agent responses one criterion at a time using LLM-as-judge."""

    def __init__(self, api_key: str = "", model: str = _DEEPSEEK_MODEL) -> None:
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self._model = model

    def evaluate_criterion(
        self,
        criterion_id: str,
        dimension: str,
        question: str,
        evidence_hint: str,
        query: str,
        response: str,
    ) -> dict[str, Any]:
        """Judge a single criterion against a response. Returns {satisfied, evidence}."""
        import requests

        prompt = _JUDGE_PROMPT.format(
            dim_upper=dimension.upper(),
            question=question,
            evidence_hint=evidence_hint,
            query=query[:500],
            response=response[:3000],
        )

        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 200,
        }

        try:
            resp = requests.post(
                _DEEPSEEK_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
                proxies={"http": None, "https": None},
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()

            # Parse JSON from response (handle markdown fences)
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("\n", 1)[0]
            result = json.loads(content)
            return {
                "criterion_id": criterion_id,
                "dimension": dimension,
                "satisfied": result.get("satisfied", False),
                "evidence": result.get("evidence", ""),
            }
        except Exception as exc:
            logger.warning("Judge failed for %s: %s", criterion_id, exc)
            return {
                "criterion_id": criterion_id,
                "dimension": dimension,
                "satisfied": False,
                "evidence": f"Judge error: {str(exc)[:100]}",
            }

    def evaluate_response(
        self,
        query: str,
        response: str,
        dimensions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Evaluate a full agent response against all criteria.

        Returns: {results: {criterion_id: bool}, scores: {dim: score}, total: N, details: [...]}
        """
        from evaluation.criterion import DIMENSION_CRITERIA, dimension_to_score, total_score

        target_dims = dimensions or list(DIMENSION_CRITERIA.keys())

        all_results: dict[str, bool] = {}
        details: list[dict[str, Any]] = []

        for dim in target_dims:
            criteria = DIMENSION_CRITERIA.get(dim, [])
            for c in criteria:
                result = self.evaluate_criterion(
                    criterion_id=c.id,
                    dimension=dim,
                    question=c.question,
                    evidence_hint=c.evidence_hint,
                    query=query,
                    response=response,
                )
                all_results[c.id] = result["satisfied"]
                details.append(result)
                logger.info("  %s: %s", c.id, "PASS" if result["satisfied"] else "FAIL")

        total, dim_scores = total_score(all_results)
        passed = sum(1 for v in all_results.values() if v)
        total_criteria = len(all_results)

        return {
            "results": all_results,
            "scores": dim_scores,
            "total_score": total,
            "total_possible": 24,
            "pass_threshold": 18,
            "passed": total >= 18,
            "criteria_checked": total_criteria,
            "criteria_passed": passed,
            "details": details,
        }
