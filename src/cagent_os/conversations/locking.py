from __future__ import annotations

import threading


class ConversationLockManager:
    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def acquire(self, conversation_id: str) -> bool:
        with self._guard:
            lock = self._locks.setdefault(conversation_id, threading.Lock())
        return lock.acquire(blocking=False)

    def release(self, conversation_id: str) -> None:
        with self._guard:
            lock = self._locks.get(conversation_id)
        if lock is not None and lock.locked():
            lock.release()
