"""Cost tracking with SQLite append-only persistence.

Design: one usage_records table (append-only → no read-modify-write race).
Quotas are computed with SELECT SUM(...) WHERE user_id AND date.

Supports:
  - Per-user daily token limit + request count limit
  - Global daily/monthly token limits (safety net)
  - Per-user concurrency limit (in-flight = 1)
  - Model-aware cost estimation (input/output rates differ)
  - source column: "user" | "cron" (cron doesn't count against user quota)
  - Telemetry piggyback: query_preview + is_follow_up
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Model pricing (per 1M tokens, approximate) ──────────────────────
# Input/output cost per token (not per 1M — computed from $/1M rates)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_token, output_per_token) — approximate
    "deepseek-chat":      (0.28 / 1_000_000, 1.10 / 1_000_000),  # DeepSeek V4
    "deepseek-reasoner":  (0.55 / 1_000_000, 2.19 / 1_000_000),  # DeepSeek R1
    "gpt-4o":             (2.50 / 1_000_000, 10.00 / 1_000_000), # GPT-4o (ballpark)
    "claude-sonnet":      (3.00 / 1_000_000, 15.00 / 1_000_000), # Claude 3.5 Sonnet
}

_FALLBACK_RATES = (0.28 / 1_000_000, 1.10 / 1_000_000)  # Default: DeepSeek V4


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost from token counts and model pricing."""
    in_rate, out_rate = _MODEL_PRICING.get(model, _FALLBACK_RATES)
    return input_tokens * in_rate + output_tokens * out_rate


class BudgetExceeded(Exception):
    """Raised when a budget limit is reached with a user-friendly message."""

    def __init__(self, message: str, retry_after_sec: int = 0) -> None:
        self.message = message
        self.retry_after_sec = retry_after_sec
        super().__init__(message)


class ConcurrencyExceeded(Exception):
    """Raised when a user already has an in-flight request."""

    def __init__(self, user_id: str) -> None:
        super().__init__(
            f"你的上一个问题还在处理中，请等它完成后再问新的。"
        )


# ── SQL schema ──────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT DEFAULT '',
    request_id TEXT DEFAULT '',
    timestamp TEXT NOT NULL,
    model TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    estimated_cost REAL DEFAULT 0.0,
    source TEXT NOT NULL DEFAULT 'user',
    query_preview TEXT DEFAULT '',
    is_follow_up INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_usage_user_date
    ON usage_records(user_id, date(timestamp));

CREATE INDEX IF NOT EXISTS idx_usage_source_date
    ON usage_records(source, date(timestamp));

CREATE INDEX IF NOT EXISTS idx_usage_session
    ON usage_records(session_id);
"""


class CostTracker:
    """Thread-safe, SQLite-backed cost tracker with per-user quotas."""

    def __init__(
        self,
        db_path: str = "data/cost_tracker.db",
        *,
        daily_token_limit: int | None = None,
        monthly_token_limit: int | None = None,
        user_daily_token_limit: int | None = None,
        user_daily_request_limit: int | None = None,
        user_max_concurrent: int = 1,
        global_max_concurrent: int = 5,
    ) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._enabled = os.getenv("COST_TRACKING_ENABLED", "true").lower() == "true"

        # Quota config (env vars with sensible defaults)
        self._daily_token_limit = (
            daily_token_limit
            if daily_token_limit is not None
            else int(os.getenv("COST_DAILY_TOKEN_LIMIT", "500000"))
        )
        self._monthly_token_limit = (
            monthly_token_limit
            if monthly_token_limit is not None
            else int(os.getenv("COST_MONTHLY_TOKEN_LIMIT", "3000000"))
        )
        self._user_daily_token_limit = (
            user_daily_token_limit
            if user_daily_token_limit is not None
            else int(os.getenv("COST_USER_DAILY_TOKEN_LIMIT", "100000"))
        )
        self._user_daily_request_limit = (
            user_daily_request_limit
            if user_daily_request_limit is not None
            else int(os.getenv("COST_USER_DAILY_REQUEST_LIMIT", "30"))
        )
        self._user_max_concurrent = int(
            os.getenv("COST_USER_MAX_CONCURRENT", str(user_max_concurrent))
        )
        self._global_max_concurrent = int(
            os.getenv("COST_GLOBAL_MAX_CONCURRENT", str(global_max_concurrent))
        )

        # ── Concurrency tracking (in-memory, single-process) ──
        # user_id → acquire timestamp (monotonic). TTL ensures self-healing
        # even if the SSE generator's finally block never executes (client
        # disconnect, GC delay, etc.).
        self._in_flight: dict[str, float] = {}
        self._lock_ttl_sec = 300  # 5 minutes — auto-release stale locks

        # ── Init DB ──
        self._init_db()
        logger.info(
            "Cost tracker ready: daily=%dK monthly=%dK user_daily=%dK user_requests=%d "
            "concurrent=%d/%d (enabled=%s)",
            self._daily_token_limit // 1000,
            self._monthly_token_limit // 1000,
            self._user_daily_token_limit // 1000,
            self._user_daily_request_limit,
            self._user_max_concurrent,
            self._global_max_concurrent,
            self._enabled,
        )

    # ── Public API ───────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def daily_limit(self) -> int:
        return self._daily_token_limit

    @property
    def monthly_limit(self) -> int:
        return self._monthly_token_limit

    @property
    def user_daily_token_limit(self) -> int:
        return self._user_daily_token_limit

    @property
    def user_daily_request_limit(self) -> int:
        return self._user_daily_request_limit

    # ── Concurrency ───────────────────────────────────────────────────

    def acquire(self, user_id: str) -> None:
        """Acquire a concurrency slot. Raises ConcurrencyExceeded if unavailable.
        
        Stale locks (older than _lock_ttl_sec) are automatically purged.
        """
        if not self._enabled:
            return
        now = time.monotonic()
        with self._lock:
            # ── Purge expired locks (self-healing) ──
            expired = [
                uid for uid, ts in self._in_flight.items()
                if now - ts > self._lock_ttl_sec
            ]
            for uid in expired:
                logger.warning("Releasing stale concurrency lock for %s (expired %ds ago)",
                               uid, int(now - self._in_flight[uid]))
                del self._in_flight[uid]

            if user_id in self._in_flight:
                raise ConcurrencyExceeded(user_id)
            if len(self._in_flight) >= self._global_max_concurrent:
                raise ConcurrencyExceeded(user_id)  # Same message for simplicity
            self._in_flight[user_id] = now

    def release(self, user_id: str) -> None:
        """Release a concurrency slot. MUST be called in a finally block."""
        if not self._enabled:
            return
        with self._lock:
            self._in_flight.pop(user_id, None)

    # ── Budget checks ────────────────────────────────────────────────

    def check_budget(self, user_id: str) -> None:
        """Check all applicable budget limits. Raises BudgetExceeded if any exceeded."""
        if not self._enabled:
            return
        today_str = date.today().isoformat()
        month_str = today_str[:7]

        with self._get_conn() as conn:
            # Per-user daily request count
            req_count = conn.execute(
                "SELECT COUNT(*) FROM usage_records WHERE user_id=? AND date(timestamp)=? AND source='user'",
                (user_id, today_str),
            ).fetchone()[0]
            if req_count >= self._user_daily_request_limit:
                raise BudgetExceeded(
                    f"今日额度已用完（{req_count}/{self._user_daily_request_limit} 次）。"
                    f"北京时间 0 点重置。需要更多可以找我。",
                    retry_after_sec=_seconds_until_midnight_cst(),
                )

            # Per-user daily token sum
            user_daily = conn.execute(
                "SELECT COALESCE(SUM(input_tokens+output_tokens), 0) FROM usage_records "
                "WHERE user_id=? AND date(timestamp)=? AND source='user'",
                (user_id, today_str),
            ).fetchone()[0]
            if user_daily >= self._user_daily_token_limit:
                raise BudgetExceeded(
                    f"今日 token 额度已用完（{user_daily:,}/{self._user_daily_token_limit:,} tokens）。"
                    f"北京时间 0 点重置。需要更多可以找我。",
                    retry_after_sec=_seconds_until_midnight_cst(),
                )

            # Global daily token sum
            global_daily = conn.execute(
                "SELECT COALESCE(SUM(input_tokens+output_tokens), 0) FROM usage_records "
                "WHERE date(timestamp)=?",
                (today_str,),
            ).fetchone()[0]
            if global_daily >= self._daily_token_limit:
                raise BudgetExceeded(
                    f"系统今日总 token 额度已用完。北京时间 0 点重置。",
                    retry_after_sec=_seconds_until_midnight_cst(),
                )

            # Global monthly token sum
            global_monthly = conn.execute(
                "SELECT COALESCE(SUM(input_tokens+output_tokens), 0) FROM usage_records "
                "WHERE strftime('%Y-%m', timestamp)=?",
                (month_str,),
            ).fetchone()[0]
            if global_monthly >= self._monthly_token_limit:
                raise BudgetExceeded(
                    f"系统本月总 token 额度已用完。需要更多可以找我。",
                )

    def record(
        self,
        user_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
        source: str = "user",
        session_id: str = "",
        request_id: str = "",
        query_preview: str = "",
        is_follow_up: bool = False,
    ) -> None:
        """Append a usage record. Thread-safe, append-only."""
        if not self._enabled:
            return
        estimated_cost = _estimate_cost(model, input_tokens, output_tokens)
        ts = datetime.now(timezone.utc).isoformat()

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO usage_records
                   (user_id, session_id, request_id, timestamp, model,
                    input_tokens, output_tokens, estimated_cost, source,
                    query_preview, is_follow_up)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id, session_id, request_id, ts, model,
                    input_tokens, output_tokens, estimated_cost, source,
                    query_preview, 1 if is_follow_up else 0,
                ),
            )

    def get_usage(self, user_id: str) -> dict:
        """Get current usage stats for a user."""
        today_str = date.today().isoformat()
        month_str = today_str[:7]

        with self._get_conn() as conn:
            user_daily = conn.execute(
                "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), "
                "COALESCE(SUM(estimated_cost),0), COUNT(*) "
                "FROM usage_records WHERE user_id=? AND date(timestamp)=? AND source='user'",
                (user_id, today_str),
            ).fetchone()
            user_monthly = conn.execute(
                "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), "
                "COALESCE(SUM(estimated_cost),0) "
                "FROM usage_records WHERE user_id=? AND strftime('%Y-%m', timestamp)=? AND source='user'",
                (user_id, month_str),
            ).fetchone()
            global_daily = conn.execute(
                "SELECT COALESCE(SUM(input_tokens+output_tokens),0) "
                "FROM usage_records WHERE date(timestamp)=?",
                (today_str,),
            ).fetchone()[0]
            global_monthly = conn.execute(
                "SELECT COALESCE(SUM(input_tokens+output_tokens),0) "
                "FROM usage_records WHERE strftime('%Y-%m', timestamp)=?",
                (month_str,),
            ).fetchone()[0]
            concurrent = len(self._in_flight)

        return {
            "tracking_enabled": self._enabled,
            "concurrent": concurrent,
            "user": {
                "daily": {
                    "requests": user_daily[3],
                    "request_limit": self._user_daily_request_limit,
                    "input_tokens": user_daily[0],
                    "output_tokens": user_daily[1],
                    "total_tokens": user_daily[0] + user_daily[1],
                    "token_limit": self._user_daily_token_limit,
                    "estimated_cost_usd": round(user_daily[2], 6),
                },
                "monthly": {
                    "input_tokens": user_monthly[0],
                    "output_tokens": user_monthly[1],
                    "total_tokens": user_monthly[0] + user_monthly[1],
                    "estimated_cost_usd": round(user_monthly[2], 6),
                },
            },
            "global": {
                "daily": {"total_tokens": global_daily, "token_limit": self._daily_token_limit},
                "monthly": {"total_tokens": global_monthly, "token_limit": self._monthly_token_limit},
            },
        }

    # ── Telemetry (query-level) ──────────────────────────────────────

    def record_query(
        self,
        user_id: str,
        *,
        query: str,
        session_id: str = "",
        request_id: str = "",
        is_follow_up: bool = False,
    ) -> None:
        """Record a query before LLM calls (separate from token recording).
        
        Called at request start so we have the query text even if the LLM 
        call fails mid-way or the request is rate-limited. Token info will 
        be appended via record() later.
        """
        if not self._enabled:
            return
        ts = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO usage_records
                   (user_id, session_id, request_id, timestamp, model,
                    input_tokens, output_tokens, estimated_cost, source,
                    query_preview, is_follow_up)
                   VALUES (?, ?, ?, ?, 'query_only', 0, 0, 0.0, 'user', ?, ?)""",
                (user_id, session_id, request_id, ts, query, 1 if is_follow_up else 0),
            )

    # ── Internal ─────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _get_conn(self):
        """Get a thread-safe SQLite connection in WAL mode."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _seconds_until_midnight_cst() -> int:
    """Seconds until midnight Beijing time (UTC+8)."""
    now_utc = datetime.now(timezone.utc)
    # Beijing midnight = UTC 16:00 previous day
    cst_midnight_utc = now_utc.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_utc.hour >= 16:
        # Past today's Beijing midnight → next day
        from datetime import timedelta
        cst_midnight_utc += timedelta(days=1)
    delta = cst_midnight_utc - now_utc
    return max(int(delta.total_seconds()), 60)  # At least 60s
