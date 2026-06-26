"""Vector store — NumPy-backed storage for RAG retrieval.

Uses NumPy for similarity search. For 1K-10K vectors this is faster
than FAISS/ChromaDB (no C extension overhead) and works on any platform.

Phase 4: migrate to PostgreSQL + pgvector for multi-user/production.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_INDEX_FILE = "vectors.npy"
_META_FILE = "metadata.json"


class VectorStore:
    """NumPy-backed vector store for RAG."""

    def __init__(self, db_path: str | Path = "data/vectors", dimension: int = 1024) -> None:
        self._path = Path(db_path)
        self._path.mkdir(parents=True, exist_ok=True)
        self._dimension = dimension

        self._vectors: np.ndarray | None = None   # shape: (n, dim)
        self._documents: list[str] = []             # original text
        self._metadata: list[dict[str, Any]] = []   # metadata per vector

        self._load()

    def _load(self) -> None:
        vec_file = str(self._path / _INDEX_FILE)
        meta_file = str(self._path / _META_FILE)
        if os.path.exists(vec_file) and os.path.exists(meta_file):
            self._vectors = np.load(vec_file)
            with open(meta_file, encoding="utf-8") as f:
                saved = json.load(f)
                self._documents = saved.get("documents", [])
                self._metadata = saved.get("metadata", [])
            logger.info("Loaded %d vectors (dim=%d)", len(self._vectors), self._vectors.shape[1])
        else:
            self._vectors = np.empty((0, self._dimension), dtype=np.float32)
            logger.info("Created empty vector store (dim=%d)", self._dimension)

    def _save(self) -> None:
        if self._vectors is not None:
            np.save(str(self._path / _INDEX_FILE), self._vectors)
            with open(str(self._path / _META_FILE), "w", encoding="utf-8") as f:
                json.dump({"documents": self._documents, "metadata": self._metadata}, f, ensure_ascii=False)

    @property
    def count(self) -> int:
        return len(self._vectors) if self._vectors is not None else 0

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add vectors (replaces any existing with same index)."""
        if not ids:
            return

        new_vecs = np.array(embeddings, dtype=np.float32)
        # L2 normalize for cosine similarity
        norms = np.linalg.norm(new_vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        new_vecs = new_vecs / norms

        if self._vectors is not None and len(self._vectors) > 0:
            self._vectors = np.vstack([self._vectors, new_vecs])
        else:
            self._vectors = new_vecs

        self._documents.extend(documents)
        if metadatas:
            self._metadata.extend(metadatas)
        else:
            self._metadata.extend([{}] * len(documents))

        self._save()
        logger.info("Added %d vectors (total: %d)", len(ids), self.count)

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 20,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Cosine similarity search. Returns top-n results."""
        if self._vectors is None or len(self._vectors) == 0:
            return []

        q = np.array([query_embedding], dtype=np.float32)
        q = q / (np.linalg.norm(q) + 1e-10)

        # Cosine similarity = dot product on normalized vectors
        scores = np.dot(self._vectors, q.T).flatten()
        top_k = min(n_results, len(scores))
        if top_k == 0:
            return []

        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            i = int(idx)
            score = float(scores[i])

            meta = self._metadata[i] if i < len(self._metadata) else {}

            # Metadata filter
            if where:
                skip = False
                for k, v in where.items():
                    if meta.get(k) != v:
                        skip = True
                        break
                if skip:
                    continue

            results.append({
                "id": str(i),
                "text": self._documents[i] if i < len(self._documents) else "",
                "metadata": meta,
                "distance": 1.0 - score,
                "similarity": max(0.0, min(1.0, score)),
            })

        return results

    def clear(self) -> None:
        self._vectors = np.empty((0, self._dimension), dtype=np.float32)
        self._documents = []
        self._metadata = []
        self._save()
        logger.info("Vector store cleared")
