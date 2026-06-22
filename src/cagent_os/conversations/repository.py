from __future__ import annotations

from typing import Protocol

from cagent_os.conversations.models import JournalEntry, SessionSnapshot


class ConversationRepository(Protocol):
    def create(self, record: SessionSnapshot) -> SessionSnapshot:
        ...

    def get(self, conversation_id: str) -> SessionSnapshot:
        ...


class EventStore(Protocol):
    def append(self, conversation_id: str, event: JournalEntry) -> None:
        ...

    def list_events(self, conversation_id: str) -> list[JournalEntry]:
        ...


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self._records: dict[str, SessionSnapshot] = {}
        self._events: dict[str, list[JournalEntry]] = {}

    def create(self, record: SessionSnapshot) -> SessionSnapshot:
        self._records[record.conversation_id] = record
        self._events.setdefault(record.conversation_id, [])
        return record

    def get(self, conversation_id: str) -> SessionSnapshot:
        return self._records[conversation_id]

    def append(self, conversation_id: str, event: JournalEntry) -> None:
        self._events.setdefault(conversation_id, []).append(event)

    def list_events(self, conversation_id: str) -> list[JournalEntry]:
        return list(self._events.get(conversation_id, []))
