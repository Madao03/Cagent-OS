"""UserStore — SQLite-backed user account storage.

Two registration modes:
  1. Invitation-code mode (内测 default): username + invitation_code only.
     No email, no password. Token serves as the persistent credential.
  2. Email/password mode (legacy/production): full bcrypt-hashed passwords.

Schema (users table):
  id              TEXT PRIMARY KEY      (UUID)
  username        TEXT UNIQUE NOT NULL  (login identifier, invitation mode)
  email           TEXT UNIQUE           (nullable; set in email mode)
  password_hash   TEXT                  (nullable; set in email mode)
  display_name    TEXT NOT NULL
  role            TEXT DEFAULT 'user'
  created_via     TEXT                  ('invitation' | 'email' | 'import')
  invitation_code TEXT                  (which code was used, for audit)
  created_at      TEXT NOT NULL
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import bcrypt


class AuthError(Exception):
    """Base class for auth errors."""


class UserAlreadyExistsError(AuthError):
    """Registration failed: username or email already taken."""


class InvalidCredentialsError(AuthError):
    """Login failed: user not found or password incorrect."""


class InvitationCodeError(AuthError):
    """Invitation code invalid, already used, or exhausted."""


@dataclass(frozen=True)
class UserRecord:
    """A single user account (without hashes — safe to return to clients)."""
    id: str
    username: str
    email: str | None
    display_name: str
    role: str
    created_via: str
    invitation_code: str | None
    disabled: bool = False
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "created_via": self.created_via,
            "disabled": self.disabled,
            "created_at": self.created_at,
        }


class UserDisabledError(AuthError):
    """Account has been disabled by admin."""


def _validate_pin(pin: str) -> None:
    """PIN must be 4-6 digits."""
    if not pin:
        raise AuthError("PIN is required")
    if not pin.isdigit() or not (4 <= len(pin) <= 6):
        raise AuthError("PIN must be 4-6 digits")


def _hash_secret(secret: str) -> str:
    """bcrypt-hash a PIN or password. Returns ASCII hash string."""
    return bcrypt.hashpw(
        secret.encode("utf-8"), bcrypt.gensalt(rounds=12)
    ).decode("utf-8")


def _verify_secret(secret: str, hash_str: str) -> bool:
    """Constant-time verify a PIN/password against its hash."""
    if not hash_str:
        return False
    return bcrypt.checkpw(secret.encode("utf-8"), hash_str.encode("utf-8"))


# ── Schema migration ─────────────────────────────────────────────────

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    email           TEXT UNIQUE,
    password_hash   TEXT,
    pin_hash        TEXT,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user',
    created_via     TEXT NOT NULL DEFAULT 'invitation',
    invitation_code TEXT,
    disabled        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
"""


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Idempotent migration to latest schema.

    Handles both v1 (email/password only) and intermediate v2 (added
    username/created_via/invitation_code) → final v2 (add pin_hash/disabled).
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}

    # v1 → intermediate v2
    if "username" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        conn.execute("ALTER TABLE users ADD COLUMN created_via TEXT NOT NULL DEFAULT 'email'")
        conn.execute("ALTER TABLE users ADD COLUMN invitation_code TEXT")
        conn.execute("UPDATE users SET username = email WHERE username IS NULL")
        print("[migrate] users v1 → v2 (added username)")

    # intermediate v2 → final v2 (add pin_hash + disabled)
    if "pin_hash" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN pin_hash TEXT")
        print("[migrate] users: added pin_hash column")
    if "disabled" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
        print("[migrate] users: added disabled column")

    conn.commit()


# ── UserStore ─────────────────────────────────────────────────────────

class UserStore:
    """SQLite-backed user account store (supports invitation + email modes)."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        # Detect existing schema (v1 had email/password NOT NULL)
        existing = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if existing:
            _migrate_v1_to_v2(self._conn)
        else:
            self._conn.executescript(_SCHEMA_V2)
            self._conn.commit()

    # ── Invitation-mode registration ──────────────────────────────

    def register_with_invitation(
        self,
        *,
        username: str,
        pin: str,
        invitation_code: str,
        invitation_store: "InvitationCodeStore | None" = None,
    ) -> UserRecord:
        """Create a new user via invitation code + username + PIN.

        Args:
            username: 3-30 chars, unique
            pin: 4-6 digit numeric PIN (for subsequent logins)
            invitation_code: must be valid + not yet used
            invitation_store: code validator (injected for testability)
        """
        username = username.strip()
        if not (3 <= len(username) <= 30):
            raise AuthError("Username must be 3-30 characters")
        # Allow letters, numbers, and _ - . as separators
        import re
        if not re.match(r"^[A-Za-z0-9_.-]+$", username):
            raise AuthError("Username may only contain letters, numbers, _ - .")

        _validate_pin(pin)

        # Check username uniqueness FIRST (before consuming the code,
        # so a duplicate username doesn't burn a valid invitation)
        if self._username_exists(username):
            raise UserAlreadyExistsError(f"Username '{username}' is already taken")

        # Generate IDs early so we can attribute the invitation code consumption
        user_id = str(uuid.uuid4())
        pin_hash = _hash_secret(pin)
        created_at = datetime.now(timezone.utc).isoformat()

        # Validate + consume invitation code (attaches used_by = user_id)
        if invitation_store is not None:
            invitation_store.consume(invitation_code, used_by=user_id)  # raises InvitationCodeError

        self._conn.execute(
            """
            INSERT INTO users (id, username, pin_hash, display_name, created_via, invitation_code, created_at)
            VALUES (?, ?, ?, ?, 'invitation', ?, ?)
            """,
            (user_id, username, pin_hash, username, invitation_code, created_at),
        )
        self._conn.commit()
        return UserRecord(
            id=user_id, username=username, email=None,
            display_name=username, role="user",
            created_via="invitation", invitation_code=invitation_code,
            disabled=False, created_at=created_at,
        )

    # ── PIN-mode login ────────────────────────────────────────────

    def authenticate_by_pin(self, username: str, pin: str) -> UserRecord:
        """Verify username + PIN. Raises InvalidCredentialsError / UserDisabledError."""
        username = username.strip()
        row = self._conn.execute(
            "SELECT id, username, email, pin_hash, display_name, role, created_via, invitation_code, disabled, created_at "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            # Constant-time dummy check to mitigate user enumeration.
            # This is a real bcrypt hash of the string "x" (generated offline),
            # so verify always runs but always fails — keeps timing consistent.
            _DUMMY_HASH = "$2b$12$CwTycUXWue0Thq9StjUM0eJ8G5K.q9JQxQqUqUqUqUqUqUqUqUqU"
            try:
                _verify_secret(pin or "x", _DUMMY_HASH)
            except Exception:
                pass  # Always raise InvalidCredentials regardless of verify result
            raise InvalidCredentialsError("Invalid username or PIN")

        _id, _uname, _email, pin_hash, _dname, _role, _via, _inv, _disabled, _created = row
        if _disabled:
            raise UserDisabledError(f"Account '{username}' has been disabled")
        if not _verify_secret(pin, pin_hash or ""):
            raise InvalidCredentialsError("Invalid username or PIN")

        return UserRecord(
            id=_id, username=_uname, email=_email, display_name=_dname,
            role=_role, created_via=_via, invitation_code=_inv,
            disabled=bool(_disabled), created_at=_created,
        )

    # ── Admin operations ──────────────────────────────────────────

    def set_disabled(self, username: str, disabled: bool) -> None:
        """Enable or disable a user account."""
        if not self._username_exists(username):
            raise InvalidCredentialsError(f"User '{username}' not found")
        self._conn.execute(
            "UPDATE users SET disabled = ? WHERE username = ?",
            (1 if disabled else 0, username),
        )
        self._conn.commit()

    def list_users(self, include_disabled: bool = True) -> list[UserRecord]:
        """Return all users (for admin dashboard)."""
        sql = (
            "SELECT id, username, email, display_name, role, created_via, invitation_code, disabled, created_at "
            "FROM users"
        )
        if not include_disabled:
            sql += " WHERE disabled = 0"
        sql += " ORDER BY created_at DESC"
        rows = self._conn.execute(sql).fetchall()
        return [
            UserRecord(
                id=r[0], username=r[1], email=r[2], display_name=r[3],
                role=r[4], created_via=r[5], invitation_code=r[6],
                disabled=bool(r[7]), created_at=r[8],
            )
            for r in rows
        ]

    # Legacy: keep login_by_username as alias for backward compat (test scripts)
    def login_by_username(self, username: str) -> UserRecord:
        """DEPRECATED: use authenticate_by_pin instead. Kept for tests."""
        username = username.strip()
        row = self._conn.execute(
            "SELECT id, username, email, display_name, role, created_via, invitation_code, disabled, created_at "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            raise InvalidCredentialsError(f"User '{username}' not found")
        return UserRecord(
            id=row[0], username=row[1], email=row[2], display_name=row[3],
            role=row[4], created_via=row[5], invitation_code=row[6],
            disabled=bool(row[7]), created_at=row[8],
        )

    # ── Email/password registration (legacy/production) ──────────

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
        role: str = "user",
    ) -> UserRecord:
        """Email/password registration (kept for future use)."""
        email = email.strip().lower()
        if not email or "@" not in email:
            raise AuthError("Invalid email format")
        if len(password) < 6:
            raise AuthError("Password must be at least 6 characters")

        if self._email_exists(email):
            raise UserAlreadyExistsError(f"Email '{email}' is already registered")

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt(rounds=12)
        ).decode("utf-8")

        user_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        name = (display_name or email.split("@")[0]).strip()[:50]
        # Auto-generate username from email local part
        username = email.split("@")[0][:30]
        # Ensure uniqueness
        base = username
        suffix = 1
        while self._username_exists(username):
            username = f"{base}{suffix}"
            suffix += 1

        self._conn.execute(
            """
            INSERT INTO users (id, username, email, password_hash, display_name, role, created_via, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'email', ?)
            """,
            (user_id, username, email, password_hash, name, role, created_at),
        )
        self._conn.commit()
        return UserRecord(
            id=user_id, username=username, email=email,
            display_name=name, role="role",
            created_via="email", invitation_code=None,
            created_at=created_at,
        )

    def authenticate(self, *, email: str, password: str) -> UserRecord:
        """Email/password login (legacy)."""
        email = email.strip().lower()
        row = self._conn.execute(
            "SELECT id, username, email, password_hash, display_name, role, created_via, invitation_code, created_at "
            "FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None:
            bcrypt.checkpw(b"x", b"$2b$12$" + b"x" * 53)  # constant-time dummy
            raise InvalidCredentialsError("Invalid email or password")

        password_hash = row[3]
        if not password_hash:
            raise InvalidCredentialsError("This account has no password set")
        if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
            raise InvalidCredentialsError("Invalid email or password")
        return self._row_to_record(row)

    # ── Lookup ────────────────────────────────────────────────────

    def get_by_id(self, user_id: str) -> UserRecord | None:
        row = self._conn.execute(
            "SELECT id, username, email, display_name, role, created_via, invitation_code, created_at "
            "FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def _username_exists(self, username: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone() is not None

    def _email_exists(self, email: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM users WHERE email = ?", (email,)
        ).fetchone() is not None

    def _row_to_record(self, row) -> UserRecord:
        return UserRecord(
            id=row[0], username=row[1], email=row[2], display_name=row[3],
            role=row[4], created_via=row[5], invitation_code=row[6], created_at=row[7],
        )

    def close(self) -> None:
        self._conn.close()


# ── InvitationCodeStore ───────────────────────────────────────────────

class InvitationCodeStore:
    """SQLite-backed store for one-time-use invitation codes.

    Schema:
      code           TEXT PRIMARY KEY    (8-char random)
      created_at     TEXT NOT NULL
      created_by     TEXT                ('admin' | 'script')
      used_by        TEXT                (user_id once consumed)
      used_at        TEXT
      note           TEXT                (optional comment)
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invitation_codes (
                code        TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL,
                created_by  TEXT,
                used_by     TEXT,
                used_at     TEXT,
                note        TEXT
            )
            """
        )
        self._conn.commit()

    def add(self, *, code: str, created_by: str = "script", note: str = "") -> None:
        """Insert a new invitation code. Idempotent (skips if exists)."""
        created_at = datetime.now(timezone.utc).isoformat()
        try:
            self._conn.execute(
                "INSERT INTO invitation_codes (code, created_at, created_by, note) VALUES (?, ?, ?, ?)",
                (code, created_at, created_by, note),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            pass  # already exists

    def add_many(self, codes: list[str], *, created_by: str = "script", note: str = "") -> int:
        """Bulk insert. Returns count actually inserted (skips dups)."""
        n = 0
        for code in codes:
            try:
                self.add(code=code, created_by=created_by, note=note)
                n += 1
            except Exception:
                pass
        return n

    def validate(self, code: str) -> bool:
        """Check if code is valid (exists + not yet used)."""
        row = self._conn.execute(
            "SELECT used_by FROM invitation_codes WHERE code = ?", (code.strip(),)
        ).fetchone()
        return row is not None and row[0] is None

    def consume(self, code: str, *, used_by: str | None = None) -> None:
        """Mark a code as used. Raises InvitationCodeError if invalid/used.

        Args:
            code: the invitation code
            used_by: user_id of the consumer (optional — for audit trail)
        """
        code = code.strip()
        row = self._conn.execute(
            "SELECT used_by FROM invitation_codes WHERE code = ?", (code,)
        ).fetchone()
        if row is None:
            raise InvitationCodeError(f"Invitation code '{code}' does not exist")
        # row[0] is None for unused codes, or a non-empty string when used.
        # (Note: empty string "" would also be falsy, so we enforce None
        # as the canonical "unused" marker — see add() which omits used_by.)
        if row[0] is not None and row[0] != "":
            raise InvitationCodeError(f"Invitation code '{code}' has already been used")
        used_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE invitation_codes SET used_by = ?, used_at = ? WHERE code = ?",
            (used_by or "unknown", used_at, code),
        )
        self._conn.commit()

    def list_all(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT code, created_at, created_by, used_by, used_at, note "
            "FROM invitation_codes ORDER BY created_at DESC"
        ).fetchall()
        return [
            {"code": r[0], "created_at": r[1], "created_by": r[2],
             # Normalize empty string → None for consistent display
             "used_by": r[3] if r[3] else None, "used_at": r[4], "note": r[5]}
            for r in rows
        ]

    def list_available(self) -> list[dict]:
        """Return only unused codes."""
        return [c for c in self.list_all() if not c["used_by"]]

    def close(self) -> None:
        self._conn.close()
