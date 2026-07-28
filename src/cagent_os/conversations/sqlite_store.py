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

    def list_conversations(
        self,
        *,
        principal_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List conversations with metadata for sidebar rendering.

        Returns a list of dicts:
          {
            "conversation_id": str,
            "principal_id": str,
            "user_id": str,
            "created_at": str (ISO),     # from first event
            "last_activity_at": str (ISO), # from latest event
            "last_user_message": str,      # preview of last user msg
            "first_user_message": str,     # first user msg (sidebar title)
            "event_count": int,
          }

        Args:
            principal_id: filter by principal (user identity). When None,
                returns all conversations.
            limit: cap number of results (most recent first).
        """
        # We join conversations with a few aggregate stats from events.
        # `event_json LIKE '%"type":"message.user_added"%'` would be
        # expensive — instead we pull the latest user message per conv
        # via a correlated subquery. Keep it simple for MVP.
        if principal_id is not None:
            rows = self._conn.execute(
                """
                SELECT c.conversation_id, c.principal_id, c.user_id,
                       (SELECT event_json FROM events e
                        WHERE e.conversation_id = c.conversation_id
                        ORDER BY e.id ASC LIMIT 1) AS first_event,
                       (SELECT event_json FROM events e
                        WHERE e.conversation_id = c.conversation_id
                        ORDER BY e.id DESC LIMIT 1) AS last_event,
                       (SELECT COUNT(*) FROM events e
                        WHERE e.conversation_id = c.conversation_id) AS event_count,
                       (SELECT event_json FROM events e
                        WHERE e.conversation_id = c.conversation_id
                          AND e.event_json LIKE '%"message.user_added"%'
                        ORDER BY e.id DESC LIMIT 1) AS last_user_evt,
                       (SELECT event_json FROM events e
                        WHERE e.conversation_id = c.conversation_id
                          AND e.event_json LIKE '%"message.user_added"%'
                        ORDER BY e.id ASC LIMIT 1) AS first_user_evt
                FROM conversations c
                WHERE c.principal_id = ?
                ORDER BY (SELECT MAX(id) FROM events e
                         WHERE e.conversation_id = c.conversation_id) DESC
                LIMIT ?
                """,
                (principal_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT c.conversation_id, c.principal_id, c.user_id,
                       (SELECT event_json FROM events e
                        WHERE e.conversation_id = c.conversation_id
                        ORDER BY e.id ASC LIMIT 1) AS first_event,
                       (SELECT event_json FROM events e
                        WHERE e.conversation_id = c.conversation_id
                        ORDER BY e.id DESC LIMIT 1) AS last_event,
                       (SELECT COUNT(*) FROM events e
                        WHERE e.conversation_id = c.conversation_id) AS event_count,
                       (SELECT event_json FROM events e
                        WHERE e.conversation_id = c.conversation_id
                          AND e.event_json LIKE '%"message.user_added"%'
                        ORDER BY e.id DESC LIMIT 1) AS last_user_evt,
                       (SELECT event_json FROM events e
                        WHERE e.conversation_id = c.conversation_id
                          AND e.event_json LIKE '%"message.user_added"%'
                        ORDER BY e.id ASC LIMIT 1) AS first_user_evt
                FROM conversations c
                ORDER BY (SELECT MAX(id) FROM events e
                         WHERE e.conversation_id = c.conversation_id) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        results: list[dict] = []
        for row in rows:
            conv_id, p_id, u_id, first_evt, last_evt, evt_count, last_user_evt, first_user_evt = row
            first_data = json.loads(first_evt) if first_evt else {}
            last_data = json.loads(last_evt) if last_evt else {}
            last_user_data = json.loads(last_user_evt) if last_user_evt else {}
            first_user_data = json.loads(first_user_evt) if first_user_evt else {}
            # Pull timestamps from event data if present; fall back to ""
            created_at = first_data.get("data", {}).get("timestamp", "")
            last_activity_at = last_data.get("data", {}).get("timestamp", "")
            last_user_msg = (last_user_data.get("content") or "").strip()
            first_user_msg = (first_user_data.get("content") or "").strip()
            # Truncate for preview
            if len(last_user_msg) > 80:
                last_user_msg = last_user_msg[:77] + "..."
            if len(first_user_msg) > 80:
                first_user_msg = first_user_msg[:77] + "..."

            results.append({
                "conversation_id": conv_id,
                "principal_id": p_id,
                "user_id": u_id,
                "created_at": created_at,
                "last_activity_at": last_activity_at,
                "last_user_message": last_user_msg,
                "first_user_message": first_user_msg,
                "event_count": evt_count,
            })
        return results

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
