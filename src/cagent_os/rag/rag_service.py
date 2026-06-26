"""RAG service — integrate chunker + embedder + vector store.

Two operations:
  - ingest(knowledge_dir): full ingestion (chunk → embed → store)
  - search(query, top_k): retrieve relevant chunks

Usage:
  from cagent_os.rag.rag_service import RAGService

  service = RAGService()
  service.ingest("knowledge")                    # one-time ingestion
  results = service.search("NVDA Forward PE")     # retrieve Top-5
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from cagent_os.rag.chunker import Chunk, scan_knowledge_base
from cagent_os.rag.embedder import Embedder
from cagent_os.rag.reranker import Reranker
from cagent_os.rag.retry import FailedChunkTracker
from cagent_os.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)


class RAGService:
    """Orchestrates chunking, embedding, storage, retrieval, and reranking."""

    def __init__(
        self,
        knowledge_dir: str | Path = "knowledge",
        chroma_path: str | Path = "data/faiss",
        api_key: str | None = None,
        enable_rerank: bool = True,
    ) -> None:
        self._knowledge_dir = Path(knowledge_dir)
        self._embedder = Embedder(api_key=api_key)
        self._store = VectorStore(db_path=chroma_path, dimension=self._embedder.dimensions)
        self._reranker = Reranker(api_key=api_key) if enable_rerank else None

    @property
    def chunk_count(self) -> int:
        return self._store.count

    @property
    def embedder_model(self) -> str:
        return self._embedder.model_name

    @property
    def status(self) -> dict[str, Any]:
        """Return RAG system status for agent introspection."""
        return {
            "available": self._store.count > 0,
            "chunks": self._store.count,
            "embedding_model": self._embedder.model_name,
            "dimensions": self._embedder.dimensions,
            "knowledge_dir": str(self._knowledge_dir),
        }

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest(self, clear_first: bool = True) -> dict[str, int]:
        """Full ingestion: scan → chunk → embed → store (incremental).

        Each successful batch is stored immediately — if a later batch fails,
        earlier batches are already persisted. No "all or nothing" rollback.

        Returns:
            {"total": N, "stored": N, "failed": N}
        """
        if clear_first:
            self._store.clear()

        tracker = FailedChunkTracker()

        # Step 1: Chunk
        logger.info("Step 1: Scanning knowledge base at %s", self._knowledge_dir)
        chunks = scan_knowledge_base(self._knowledge_dir)
        if not chunks:
            logger.warning("No chunks found. Aborting ingestion.")
            return {"total": 0, "stored": 0, "failed": 0}

        total = len(chunks)
        logger.info("Step 1 complete: %d chunks", total)

        # Step 2+3: Embed → store batch-by-batch (incremental save)
        logger.info("Step 2+3: Embedding & storing %d chunks with %s (batch=%d, incremental)",
                     total, self._embedder.model_name, self._embedder._batch_size)

        texts = [c.text for c in chunks]
        stored_count = 0
        failed_count = 0

        batch_size = self._embedder._batch_size
        total_batches = (total + batch_size - 1) // batch_size

        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch_texts = texts[batch_start:batch_end]
            batch_chunks = chunks[batch_start:batch_end]
            batch_num = batch_start // batch_size + 1

            # ── Embed this batch ──
            batch_vectors = None
            batch_error = ""
            try:
                batch_vectors = self._embedder.embed_batch(batch_texts)
            except Exception as exc:
                batch_error = str(exc)[:200]
                logger.error("Batch %d/%d embed FAILED: %s", batch_num, total_batches, batch_error)

            if batch_vectors is None or not batch_vectors:
                # ── Embed failed → log & skip ──
                batch_ids = [c.id for c in batch_chunks]
                tracker.log_failed(batch_ids, batch_texts, batch_error, batch_num)
                failed_count += len(batch_chunks)
                continue

            # ── Embed succeeded → store IMMEDIATELY ──
            try:
                batch_ids = [c.id for c in batch_chunks]
                batch_docs = [c.text for c in batch_chunks]
                batch_metas = [
                    {
                        "source": c.source, "title": c.title,
                        "section": c.section, "chunk_type": c.chunk_type,
                        "date": c.date, "parent_index": c.parent_index,
                        "embedding_model": self._embedder.model_name,
                    }
                    for c in batch_chunks
                ]
                self._store.add(ids=batch_ids, embeddings=batch_vectors, documents=batch_docs, metadatas=batch_metas)
                stored_count += len(batch_chunks)
                logger.info("Batch %d/%d stored: %d chunks (total: %d/%d)",
                             batch_num, total_batches, len(batch_chunks), stored_count, total)
            except Exception as exc:
                # ── Store failed → log for retry ──
                batch_error = f"Store error: {str(exc)[:200]}"
                logger.error("Batch %d/%d store FAILED: %s", batch_num, total_batches, batch_error)
                batch_ids = [c.id for c in batch_chunks]
                tracker.log_failed(batch_ids, batch_texts, batch_error, batch_num)
                failed_count += len(batch_chunks)

        logger.info("Ingestion complete: %d/%d stored, %d failed, %d tokens",
                     stored_count, total, failed_count, self._embedder.total_tokens_used)

        if failed_count > 0:
            logger.warning(
                "%d chunks failed. Run retry_failed() to reattempt. Log: data/vectors/failed_chunks.jsonl",
                failed_count,
            )

        return {"total": total, "stored": stored_count, "failed": failed_count}

    def retry_failed(self) -> dict[str, int]:
        """Retry embedding previously failed chunks.

        Returns:
            {"retried": N, "resolved": N, "still_failed": N}
        """
        tracker = FailedChunkTracker()
        pending = tracker.get_pending()
        if not pending:
            logger.info("No pending failed chunks to retry")
            return {"retried": 0, "resolved": 0, "still_failed": 0}

        logger.info("Retrying %d failed chunks", len(pending))
        texts = [p["text_preview"] for p in pending]
        chunk_ids = [p["chunk_id"] for p in pending]
        tracker.mark_retried(chunk_ids)

        vectors, failed_indices = self._embedder.embed_all(texts)
        failed_set = set(failed_indices)

        resolved_ids = [cid for i, cid in enumerate(chunk_ids) if i not in failed_set]
        still_failed_ids = [cid for i, cid in enumerate(chunk_ids) if i in failed_set]

        if resolved_ids:
            # Store successfully retried chunks
            resolved_chunks = []
            for i, entry in enumerate(pending):
                if i not in failed_set and vectors[i]:
                    resolved_chunks.append((entry, vectors[i]))
            if resolved_chunks:
                self._store.add(
                    ids=[e["chunk_id"] for e, _ in resolved_chunks],
                    embeddings=[v for _, v in resolved_chunks],
                    documents=[e.get("text_preview", "") for e, _ in resolved_chunks],
                )
            tracker.mark_resolved(resolved_ids)

        if still_failed_ids:
            logger.warning("%d chunks still failed after retry", len(still_failed_ids))

        return {
            "retried": len(pending),
            "resolved": len(resolved_ids),
            "still_failed": len(still_failed_ids),
        }

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
        use_rerank: bool = True,
    ) -> list[dict[str, Any]]:
        """Search for chunks relevant to query with optional reranking.

        Pipeline:
          1. Embed query → vector
          2. Vector search → Top-20 candidates (fast, coarse)
          3. Rerank → Top-5 (slow, precise)

        Args:
            query: user query text
            top_k: final number of results to return
            where: optional metadata filter
            use_rerank: enable reranking (default True)

        Returns:
            List of {id, text, metadata, similarity, rerank_score?} sorted by relevance.
        """
        query_vector = self._embedder.embed_query(query)
        if not query_vector:
            logger.warning("Empty query embedding for: %s", query[:50])
            return []

        # Stage 1: Vector retrieval (coarse, fast)
        candidates = self._store.query(
            query_embedding=query_vector,
            n_results=max(20, top_k * 4),
            where=where,
        )
        if not candidates:
            return []

        # Stage 2: Rerank (precise, slower) — optional
        if use_rerank and self._reranker is not None and len(candidates) > top_k:
            try:
                docs = [r["text"][:1500] for r in candidates]
                reranked = self._reranker.rerank(query, docs, top_n=top_k)
                results = []
                for rr in reranked:
                    idx = rr.get("index", 0)
                    if idx < len(candidates):
                        r = dict(candidates[idx])
                        r["rerank_score"] = rr.get("relevance_score", 0)
                        r["search_stage"] = "reranked"
                        results.append(r)
                logger.info("RAG: %d → rerank → %d (query: %s)", len(candidates), len(results), query[:50])
                return results
            except Exception as exc:
                logger.warning("Rerank failed, falling back to vector-only: %s", exc)

        # Fallback: vector-only results
        results = [dict(r) for r in candidates[:top_k]]
        for r in results:
            r["search_stage"] = "vector_only"
        logger.info("RAG: %d results (vector-only, query: %s)", len(results), query[:50])
        return results

    def format_context(self, results: list[dict[str, Any]], max_results: int = 5) -> str:
        """Format search results into a system prompt section.

        Args:
            results: output from search()
            max_results: max number of results to include

        Returns:
            Formatted markdown string for prompt injection.
        """
        if not results:
            return ""

        top = results[:max_results]
        lines = ["## Retrieved Knowledge (RAG)"]
        lines.append("以下是从知识库中检索到的与本次查询相关的内容片段:\n")

        for i, r in enumerate(top, 1):
            meta = r.get("metadata", {})
            title = meta.get("title", "Unknown")
            date = meta.get("date", "")
            section = meta.get("section", "")
            source = meta.get("source", "")
            sim = r.get("similarity", 0)

            lines.append(f"### [{i}] {title} ({date}) — 相似度 {sim:.2%}")
            if section:
                lines.append(f"*{section}*")
            lines.append(f"> {r['text'][:500]}{'...' if len(r['text']) > 500 else ''}")
            lines.append(f"*来源: {source}*\n")

        return "\n".join(lines)
