"""Failed chunk tracker + retry mechanism.

Phase 3: Network glitches, API rate limits, or transient errors can cause
individual embedding batches to fail. Instead of crashing the entire ingestion,
we log failures to a JSONL file and support incremental retry.

Usage:
  from cagent_os.rag.retry import FailedChunkTracker

  tracker = FailedChunkTracker("data/vectors/failed_chunks.jsonl")

  # During ingestion: log any chunks that failed
  tracker.log_failed(chunks_batch, error_msg)

  # After ingestion: retry failed chunks
  pending = tracker.get_pending()  # unresolved failures
  tracker.mark_resolved(chunk_ids)  # after successful retry
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class FailedChunkTracker:
    """Append-only JSONL log of failed embedding chunks with retry support."""

    def __init__(self, log_path: str | Path = "data/vectors/failed_chunks.jsonl") -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def log_failed(
        self,
        chunk_ids: list[str],
        texts: list[str],
        error: str,
        batch_index: int = -1,
    ) -> int:
        """Log a batch of failed chunks. Returns number of entries written."""
        if not chunk_ids:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        count = 0
        with open(self._path, "a", encoding="utf-8") as f:
            for i, cid in enumerate(chunk_ids):
                entry = {
                    "chunk_id": cid,
                    "text_preview": texts[i][:200] if i < len(texts) else "",
                    "error": error[:500],
                    "timestamp": now,
                    "batch_index": batch_index,
                    "retry_count": 0,
                    "resolved": False,
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                count += 1

        logger.warning("Logged %d failed chunks to %s (batch %d: %s)", count, self._path, batch_index, error[:100])
        return count

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_pending(self) -> list[dict]:
        """Return all unresolved failed chunks (retry_count < max_retries)."""
        if not self._path.exists():
            return []

        pending = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if not entry.get("resolved", False) and entry.get("retry_count", 0) < 3:
                        pending.append(entry)
                except json.JSONDecodeError:
                    continue

        return pending

    def get_summary(self) -> dict:
        """Return a summary of the failure log."""
        if not self._path.exists():
            return {"total_entries": 0, "pending": 0, "resolved": 0}

        total = 0
        pending = 0
        resolved = 0
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    entry = json.loads(line)
                    if entry.get("resolved", False):
                        resolved += 1
                    else:
                        pending += 1
                except json.JSONDecodeError:
                    pass

        return {"total_entries": total, "pending": pending, "resolved": resolved}

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def mark_retried(self, chunk_ids: list[str]) -> None:
        """Increment retry_count for specified chunks (called before retry attempt)."""
        self._update(chunk_ids, increment_retry=True)

    def mark_resolved(self, chunk_ids: list[str]) -> None:
        """Mark specified chunks as resolved (called after successful retry)."""
        self._update(chunk_ids, mark_resolved=True)

    def _update(self, chunk_ids: list[str], increment_retry: bool = False, mark_resolved: bool = False) -> None:
        """Rewrite the log file with updated entries."""
        if not self._path.exists():
            return

        target = set(chunk_ids)
        updated = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("chunk_id") in target:
                        if increment_retry:
                            entry["retry_count"] = entry.get("retry_count", 0) + 1
                        if mark_resolved:
                            entry["resolved"] = True
                            entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
                    updated.append(entry)
                except json.JSONDecodeError:
                    updated.append({"raw": line})

        with open(self._path, "w", encoding="utf-8") as f:
            for entry in updated:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        verb = "resolved" if mark_resolved else "incremented retry"
        logger.info("Updated %d entries in %s: %s", len(target), self._path, verb)

    def clear_resolved(self) -> int:
        """Remove resolved entries from the log. Returns count removed."""
        if not self._path.exists():
            return 0

        pending = []
        removed = 0
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("resolved", False):
                        removed += 1
                    else:
                        pending.append(entry)
                except json.JSONDecodeError:
                    pending.append({"raw": line})

        with open(self._path, "w", encoding="utf-8") as f:
            for entry in pending:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.info("Cleared %d resolved entries from %s (%d pending)", removed, self._path, len(pending))
        return removed
