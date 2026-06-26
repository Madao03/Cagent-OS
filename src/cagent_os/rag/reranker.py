"""Reranker — SiliconFlow Qwen3-Reranker for relevance re-ranking.

After vector search returns Top-20 candidates, the reranker scores each
(query, document) pair with a cross-attention model for much higher
precision than cosine similarity alone.

Flow:
  retrieve Top-20 → rerank(query, docs) → Top-5 → LLM context

API: SiliconFlow /v1/rerank (OpenAI-compatible)
Model: Qwen/Qwen3-Reranker
Cost: ~$0.02/1M tokens
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

_SILICONFLOW_BASE = "https://api.siliconflow.cn/v1"
_RERANK_MODEL = "Qwen/Qwen3-Reranker-8B"
_MAX_RETRIES = 2
_RETRY_DELAY = 0.5


class Reranker:
    """Re-rank search results using SiliconFlow Qwen3-Reranker."""

    def __init__(self, api_key: str | None = None, model: str = _RERANK_MODEL) -> None:
        self._api_key = api_key or os.environ.get("SILICONFLOW_API_KEY", "")
        if not self._api_key:
            raise ValueError("SILICONFLOW_API_KEY not set")
        self._model = model
        self._total_tokens = 0

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def total_tokens_used(self) -> int:
        return self._total_tokens

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 5,
        return_documents: bool = True,
    ) -> list[dict[str, Any]]:
        """Re-rank documents by relevance to query.

        Args:
            query: the user's search query
            documents: list of document texts to re-rank
            top_n: number of top results to return (default 5)
            return_documents: include original text in results

        Returns:
            List of {index, relevance_score, document?} sorted by score desc.
        """
        if not documents:
            return []

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(documents)),
            "return_documents": return_documents,
        }

        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.post(
                    f"{_SILICONFLOW_BASE}/rerank",
                    headers=headers,
                    json=payload,
                    timeout=30,
                    proxies={"http": None, "https": None},
                )
                resp.raise_for_status()
                data = resp.json()

                usage = data.get("usage", {})
                self._total_tokens += usage.get("total_tokens", 0)

                results = data.get("results", [])
                logger.info(
                    "Rerank: %d docs → %d results (tokens: %d)",
                    len(documents), len(results), usage.get("total_tokens", 0),
                )
                return results

            except requests.exceptions.RequestException as e:
                logger.warning("Rerank attempt %d failed: %s", attempt + 1, e)
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                else:
                    logger.error("Rerank failed after %d retries, returning original order", _MAX_RETRIES)
                    # Fallback: return original order
                    return [
                        {"index": i, "relevance_score": 1.0 / (i + 1), "document": {"text": d[:200]}}
                        for i, d in enumerate(documents[:top_n])
                    ]

        return []
