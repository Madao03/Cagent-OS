from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class ConversationLockManager:
    """Per-conversation re-entrancy guard.

    Prevents the same conversation from running concurrently (e.g. two
    HTTP requests for the same conversation_id). Uses one threading.Lock
    per conversation_id, stored in a dict.

    Stale locks (unlocked but not yet cleaned up) are purged on acquire
    to prevent unbounded dict growth.
    """

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def acquire(self, conversation_id: str) -> bool:
        with self._guard:
            # Purge unlocked entries to prevent unbounded growth
            stale = [cid for cid, lock in self._locks.items() if not lock.locked()]
            for cid in stale:
                del self._locks[cid]

            lock = self._locks.setdefault(conversation_id, threading.Lock())
        return lock.acquire(blocking=False)

    def release(self, conversation_id: str) -> None:
        with self._guard:
            lock = self._locks.get(conversation_id)
        if lock is not None and lock.locked():
            lock.release()
