"""User LLM key store — encrypted per-user API keys for BYOK (bring your own key).

Storage: SQLite table `user_llm_keys` with Fernet-encrypted key material.
Master secret: CAGENTOS_KEY_ENCRYPTION_SECRET env var (32-byte hex or Fernet key).
Losing the secret invalidates all stored keys (users re-enter) — acceptable.

Usage:
    store = UserLLMKeyStore(db_path)
    store.upsert(user_id, provider="openai", api_key="sk-...", default_model="gpt-4o")
    cfg = store.get(user_id)   # None if not configured
    store.delete(user_id)
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MASTER_SECRET_ENV = "CAGENTOS_KEY_ENCRYPTION_SECRET"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_llm_keys (
    user_id         TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,
    api_key_encrypted BLOB NOT NULL,
    default_model   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class UserLLMConfig:
    provider: str
    api_key: str          # decrypted, in-memory only
    default_model: str | None


def _new_fernet():
    """Build Fernet cipher from CAGENTOS_KEY_ENCRYPTION_SECRET.

    Falls back to a deterministic dev key (with warning) when unset.
    """
    secret = os.environ.get(_MASTER_SECRET_ENV, "").strip()
    if secret:
        try:
            if secret.startswith("gAAAA"):
                from cryptography.fernet import Fernet
                return Fernet(secret.encode())
            return _fernet_from_hex(secret)
        except Exception as exc:
            logger.error("Failed to build Fernet from CAGENTOS_KEY_ENCRYPTION_SECRET: %s", exc)

    # Dev fallback — NOT for production.
    logger.warning(
        "CAGENTOS_KEY_ENCRYPTION_SECRET not set — using insecure dev fallback. "
        "Set it in production: openssl rand -hex 32"
    )
    import base64
    import hashlib
    from cryptography.fernet import Fernet
    digest = hashlib.sha256(b"cagentos-dev-key-fallback").digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _fernet_from_hex(hex_str: str):
    import base64
    import binascii
    raw = binascii.unhexlify(hex_str)
    if len(raw) != 32:
        raise ValueError("hex secret must be 32 bytes (openssl rand -hex 32)")
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(raw))


def _new_fernet():
    """Clean constructor for _get_fernet (the inline version above is hard to read)."""
    secret = os.environ.get(_MASTER_SECRET_ENV, "").strip()
    if not secret:
        return None
    try:
        if secret.startswith("gAAAA"):
            from cryptography.fernet import Fernet
            return Fernet(secret.encode())
        return _fernet_from_hex(secret)
    except Exception as exc:
        logger.error("Failed to build Fernet from CAGENTOS_KEY_ENCRYPTION_SECRET: %s", exc)
        return None


class UserLLMKeyStore:
    """SQLite-backed encrypted store for per-user LLM credentials."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._fernet = _new_fernet()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def upsert(self, user_id: str, *, provider: str, api_key: str, default_model: str | None = None) -> None:
        """Store or update a user's LLM credentials (encrypted)."""
        if not provider or not api_key:
            raise ValueError("provider and api_key are required")
        encrypted = self._fernet.encrypt(api_key.encode())
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO user_llm_keys (user_id, provider, api_key_encrypted, default_model, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     provider=excluded.provider,
                     api_key_encrypted=excluded.api_key_encrypted,
                     default_model=excluded.default_model,
                     updated_at=excluded.updated_at""",
                (user_id, provider, encrypted, default_model, now, now),
            )
        logger.info("User LLM key stored user=%s provider=%s", user_id, provider)

    def get(self, user_id: str) -> UserLLMConfig | None:
        """Fetch and decrypt a user's config. Returns None if not configured."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT provider, api_key_encrypted, default_model FROM user_llm_keys WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        provider, encrypted, default_model = row
        try:
            api_key = self._fernet.decrypt(bytes(encrypted)).decode()
        except Exception:
            logger.error("Failed to decrypt user LLM key (master secret changed?) user=%s", user_id)
            return None
        return UserLLMConfig(provider=provider, api_key=api_key, default_model=default_model)

    def delete(self, user_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM user_llm_keys WHERE user_id = ?", (user_id,))
        logger.info("User LLM key deleted user=%s", user_id)

    def mask_key(self, api_key: str) -> str:
        """Return masked form for display: sk-***abc"""
        if len(api_key) <= 8:
            return "***"
        return f"{api_key[:3]}***{api_key[-4:]}"
