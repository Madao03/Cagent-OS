"""HTTP routes for RAG (knowledge base) — Phase 4c.

Exposes the RAGService to the web frontend:
  - GET  /api/v1/rag/status  → chunk count + embedding model
  - GET  /api/v1/rag/search  → query + top_k + rerank → formatted results

Design note:
  The RAGService is built once in create_app() and injected here. If it
  failed to initialize (no API key, no vectors), these endpoints return
  HTTP 503 with a helpful message instead of crashing.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)


def build_rag_router(rag_service: Any | None) -> APIRouter:
    """Construct the RAG router.

    Args:
        rag_service: initialized RAGService instance, or None when RAG
                     is unavailable (endpoints will return 503).
    """
    router = APIRouter()

    @router.get("/api/v1/rag/status")
    def rag_status() -> dict:
        """Return knowledge base status: chunk count, model, availability."""
        if rag_service is None:
            return {
                "available": False,
                "chunks": 0,
                "embedding_model": None,
                "dimensions": None,
                "reason": "RAG service not initialized (check SILICONFLOW_API_KEY and data/vectors/)",
            }
        try:
            return {
                "available": True,
                **rag_service.status,
            }
        except Exception as exc:
            logger.exception("rag_status failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/api/v1/rag/search")
    def rag_search(
        q: str = Query(..., min_length=1, description="Search query"),
        top_k: int = Query(5, ge=1, le=20, description="Number of results"),
        rerank: bool = Query(True, description="Enable reranker for precision"),
    ) -> dict:
        """Semantic search over the knowledge base.

        Returns:
        {
          "query": "...",
          "results": [
            {
              "id": "chunk-xxx",
              "text": "...",               # 200-char preview + full
              "preview": "...",            # first 200 chars
              "metadata": {...},           # source, title, etc.
              "similarity": 0.87,
              "rerank_score": 0.94,        # only when rerank=true
              "search_stage": "reranked"   # "reranked" | "vector_only"
            }
          ],
          "total": 5,
          "elapsed_ms": 1234
        }
        """
        if rag_service is None:
            raise HTTPException(
                status_code=503,
                detail="RAG service unavailable. Check SILICONFLOW_API_KEY and data/vectors/.",
            )

        import time
        started = time.perf_counter()

        try:
            raw_results = rag_service.search(q, top_k=top_k, use_rerank=rerank)
        except Exception as exc:
            logger.exception("rag_search failed for query %r: %s", q, exc)
            raise HTTPException(status_code=500, detail=f"Search failed: {exc}")

        # Shape for frontend: add preview, normalize fields
        shaped = []
        for r in raw_results:
            text = r.get("text", "") or ""
            metadata = r.get("metadata", {}) or {}
            shaped.append({
                "id": r.get("id", ""),
                "text": text,
                "preview": text[:200] + ("..." if len(text) > 200 else ""),
                "metadata": metadata,
                "source": metadata.get("source", metadata.get("file", "")),
                "title": metadata.get("title", ""),
                "similarity": float(r.get("similarity", 0) or 0),
                "rerank_score": float(r["rerank_score"]) if "rerank_score" in r else None,
                "search_stage": r.get("search_stage", "vector_only"),
            })

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "rag_search q=%r top_k=%d → %d results in %dms",
            q[:50], top_k, len(shaped), elapsed_ms,
        )

        return {
            "query": q,
            "results": shaped,
            "total": len(shaped),
            "elapsed_ms": elapsed_ms,
        }

    return router
