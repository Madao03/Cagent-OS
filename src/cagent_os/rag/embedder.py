"""Embedder — call SiliconFlow Qwen3-Embedding-8B API to vectorize text chunks.

Uses the OpenAI-compatible /v1/embeddings endpoint.
Batch size = 32 (max per request for SiliconFlow).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

# Auto-load .env for standalone use (e.g. CLI ingestion)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# SiliconFlow API
_SILICONFLOW_BASE = "https://api.siliconflow.cn/v1"
_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
_EMBEDDING_DIM = 1024
_BATCH_SIZE = 32
_MAX_RETRIES = 3
_RETRY_DELAY = 1.0  # seconds


class Embedder:
    """Batch embed text chunks via SiliconFlow Qwen3-Embedding-8B."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _EMBEDDING_MODEL,
        dimensions: int = _EMBEDDING_DIM,
        batch_size: int = _BATCH_SIZE,
    ) -> None:
        self._api_key = api_key or os.environ.get("SILICONFLOW_API_KEY", "")
        if not self._api_key:
            raise ValueError("SILICONFLOW_API_KEY not set. Set it in .env or pass api_key.")
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._total_tokens = 0
        self._total_requests = 0

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def total_tokens_used(self) -> int:
        return self._total_tokens

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts (up to batch_size). Returns list of vectors."""
        if not texts:
            return []

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "input": texts,
            "encoding_format": "float",
        }
        # Qwen3 series supports custom dimensions
        if "Qwen3" in self._model:
            payload["dimensions"] = self._dimensions

        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.post(
                    f"{_SILICONFLOW_BASE}/embeddings",
                    headers=headers,
                    json=payload,
                    timeout=60,
                    proxies={"http": None, "https": None},  # SiliconFlow is domestic, bypass proxy
                )
                resp.raise_for_status()
                data = resp.json()

                # Sort by index to ensure order matches input
                embeddings = sorted(data["data"], key=lambda x: x["index"])
                vectors = [e["embedding"] for e in embeddings]

                # Track usage
                usage = data.get("usage", {})
                self._total_tokens += usage.get("total_tokens", 0)
                self._total_requests += 1

                return vectors

            except requests.exceptions.RequestException as e:
                logger.warning("Embedding attempt %d failed: %s", attempt + 1, e)
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                else:
                    raise

        return []

    def embed_all(
        self, texts: list[str], on_batch_failed: callable | None = None
    ) -> tuple[list[list[float]], list[int]]:
        """Embed an arbitrary number of texts in batches.

        Returns:
            (vectors, failed_indices): vectors for successful batches +
            list of text indices that failed after retries.
        """
        all_vectors: list[list[float]] = []
        failed_indices: list[int] = []
        total = len(texts)

        for i in range(0, total, self._batch_size):
            batch = texts[i:i + self._batch_size]
            batch_num = i // self._batch_size + 1
            total_batches = (total + self._batch_size - 1) // self._batch_size
            logger.info("Embedding batch %d/%d (%d texts)", batch_num, total_batches, len(batch))

            try:
                vectors = self.embed_batch(batch)
                all_vectors.extend(vectors)
            except Exception as exc:
                error_msg = str(exc)[:200]
                logger.error("Batch %d/%d FAILED after %d retries: %s", batch_num, total_batches, _MAX_RETRIES, error_msg)
                # Mark these indices as failed
                batch_indices = list(range(i, min(i + self._batch_size, total)))
                failed_indices.extend(batch_indices)
                # Add placeholder Nones to keep index alignment
                all_vectors.extend([[]] * len(batch_indices))
                if on_batch_failed:
                    on_batch_failed(batch_indices, batch, error_msg, batch_num)

        logger.info(
            "Embedding complete: %d/%d texts → %d vectors (%d failed), %d tokens used",
            total - len(failed_indices), total, len(all_vectors) - len(failed_indices),
            len(failed_indices), self._total_tokens,
        )
        return all_vectors, failed_indices

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string (for retrieval)."""
        vectors = self.embed_batch([text])
        return vectors[0] if vectors else []
