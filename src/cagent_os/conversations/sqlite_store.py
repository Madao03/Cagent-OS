from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from cagent_os.conversations.models import JournalEntry, SessionSnapshot
from cagent_os.conversations.repository import ConversationRepository, EventStore


class SqliteConversationRepository(ConversationRepository, EventStore):
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS conversations ("
            "  conversation_id TEXT PRIMARY KEY,"
            "  principal_id TEXT NOT NULL,"
            "  user_id TEXT NOT NULL,"
            "  snapshot_json TEXT NOT NULL"
            ")"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  conversation_id TEXT NOT NULL,"
            "  event_json TEXT NOT NULL,"
            "  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)"
            ")"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_conversation ON events(conversation_id)"
        )
        self._conn.commit()

    def create(self, record: SessionSnapshot) -> SessionSnapshot:
        self._conn.execute(
            "INSERT INTO conversations (conversation_id, principal_id, user_id, snapshot_json) VALUES (?, ?, ?, ?)",
            (record.conversation_id, record.principal_id, record.user_id, self._serialize_record(record)),
        )
        self._conn.commit()
        return record

    def get(self, conversation_id: str) -> SessionSnapshot:
        row = self._conn.execute(
            "SELECT conversation_id, principal_id, user_id, snapshot_json FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Conversation '{conversation_id}' not found.")
        return self._deserialize_record(row[3])

    def append(self, conversation_id: str, event: JournalEntry) -> None:
        self._conn.execute(
            "INSERT INTO events (conversation_id, event_json) VALUES (?, ?)",
            (conversation_id, self._serialize_event(event)),
        )
        self._conn.commit()

    def list_events(self, conversation_id: str) -> list[JournalEntry]:
        rows = self._conn.execute(
            "SELECT event_json FROM events WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
        return [self._deserialize_event(row[0]) for row in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _serialize_record(record: SessionSnapshot) -> str:
        return json.dumps({
            "conversation_id": record.conversation_id,
            "principal_id": record.principal_id,
            "user_id": record.user_id,
        }, ensure_ascii=False)

    @staticmethod
    def _deserialize_record(raw: str) -> SessionSnapshot:
        data = json.loads(raw)
        from cagent_os.user_skills.models import UserSkillSnapshot
        return SessionSnapshot(
            conversation_id=data["conversation_id"],
            principal_id=data["principal_id"],
            user_id=data["user_id"],
            user_skill_snapshot=UserSkillSnapshot(user_id=data["user_id"]),
        )

    @staticmethod
    def _serialize_event(event: JournalEntry) -> str:
        return json.dumps({
            "type": event.type,
            "role": event.role,
            "content": event.content,
            "data": event.data,
        }, ensure_ascii=False)

    @staticmethod
    def _deserialize_event(raw: str) -> JournalEntry:
        data = json.loads(raw)
        return JournalEntry(
            type=data["type"],
            role=data.get("role"),
            content=data.get("content", ""),
            data=data.get("data", {}),
        )
