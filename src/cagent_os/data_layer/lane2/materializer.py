"""F4: Offline materialization store for EDGAR earnings releases.

SEC documents are immutable by accession — once extracted, results never change.
This store caches extraction results so agent queries hit SQLite (milliseconds)
instead of the full SEC pipeline (6+ seconds per quarter).

Cache invalidation: bump SCHEMA_VERSION when extractor logic changes.
All cached entries with an older version are automatically invalidated.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DB = "data/edgar_release.db"

# ★ Bump this when extractor/classifier logic changes.
# Cached entries with a lower version are silently invalidated (cache miss → re-extract).
SCHEMA_VERSION = 4  # v4: add source_tier to cached result

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS edgar_release_cache (
    ticker       TEXT NOT NULL,
    quarter_end  TEXT NOT NULL,          -- "2025-12-31"
    accession    TEXT NOT NULL,
    document     TEXT,
    filing_date  TEXT,
    form         TEXT,
    schema_version INTEGER NOT NULL DEFAULT 0,
    extracted_at TEXT NOT NULL,          -- ISO timestamp
    records_json TEXT,                   -- JSON array of FinancialRecord dicts
    guidance_json TEXT,                  -- JSON array of GuidanceRecord dicts
    conf         REAL,
    PRIMARY KEY (ticker, quarter_end)
);
"""

# Migration: add schema_version column to existing tables
_MIGRATE_VERSION = """
ALTER TABLE edgar_release_cache ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 0;
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_edgar_release_ticker
ON edgar_release_cache(ticker, quarter_end);
"""


class EdgarReleaseStore:
    """SQLite-backed cache for EDGAR earnings release extraction results."""

    def __init__(self, db_path: str = _DEFAULT_DB) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist, run migrations."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(_CREATE_TABLE)
            # Migration: add schema_version column (ignore error if exists)
            try:
                conn.execute(_MIGRATE_VERSION)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists
            conn.execute(_CREATE_INDEX)
            conn.commit()

    # ── Public API ──────────────────────────────────────────────

    def get(self, ticker: str, quarter_end: str) -> dict[str, Any] | None:
        """Return cached extraction result or None (if missing or stale version)."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM edgar_release_cache WHERE ticker=? AND quarter_end=?",
                (ticker.upper(), quarter_end),
            ).fetchone()

        if not row:
            return None

        # Version check: stale cache → miss (triggers re-extraction)
        cached_version = row["schema_version"]
        if cached_version < SCHEMA_VERSION:
            logger.info("Cache invalidated for %s/%s (v%d < v%d)",
                        ticker, quarter_end, cached_version, SCHEMA_VERSION)
            return None

        return {
            "success": True,
            "ticker": row["ticker"],
            "quarter_end": row["quarter_end"],
            "source": "edgar_release",
            "source_tier": "primary",
            "accession": row["accession"],
            "document": row["document"],
            "filing_date": row["filing_date"],
            "form": row["form"],
            "conf": row["conf"],
            "audited": False,
            "records": json.loads(row["records_json"] or "[]"),
            "guidance": json.loads(row["guidance_json"] or "[]"),
            "record_count": len(json.loads(row["records_json"] or "[]")),
            "guidance_count": len(json.loads(row["guidance_json"] or "[]")),
            "cached": True,
            "cached_at": row["extracted_at"],
            "execution_time": 0.0,
        }

    def put(self, ticker: str, quarter_end: str, data: dict[str, Any]) -> None:
        """Store extraction result in cache."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO edgar_release_cache
                   (ticker, quarter_end, accession, document, filing_date,
                    form, schema_version, extracted_at, records_json, guidance_json, conf)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker.upper(),
                    quarter_end,
                    data.get("accession", ""),
                    data.get("document", ""),
                    data.get("filing_date", ""),
                    data.get("form", ""),
                    SCHEMA_VERSION,
                    now,
                    json.dumps(data.get("records", []), ensure_ascii=False),
                    json.dumps(data.get("guidance", []), ensure_ascii=False),
                    data.get("conf", 0.0),
                ),
            )
            conn.commit()

    def list_ticker(self, ticker: str) -> list[dict[str, Any]]:
        """List all cached quarters for a ticker, sorted by quarter_end."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT ticker, quarter_end, accession, filing_date, conf, extracted_at "
                "FROM edgar_release_cache WHERE ticker=? ORDER BY quarter_end",
                (ticker.upper(),),
            ).fetchall()
        return [dict(r) for r in rows]

    def has(self, ticker: str, quarter_end: str) -> bool:
        """Check if a specific quarter is cached."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM edgar_release_cache WHERE ticker=? AND quarter_end=?",
                (ticker.upper(), quarter_end),
            ).fetchone()
        return row is not None

    def count(self) -> int:
        """Total cached entries."""
        with sqlite3.connect(self._db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM edgar_release_cache"
            ).fetchone()[0]
