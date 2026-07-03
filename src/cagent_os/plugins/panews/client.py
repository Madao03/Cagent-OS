"""PANews REST API client — zero-auth crypto news & Polymarket data.

Base URLs:
  - https://universal-api.panewslab.com  (articles, search, rankings, …)
  - https://polymarket-boards.panewslab.com/api/boards  (smart money)

All read endpoints are public — no API key or session token required.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

UNIVERSAL_API = "https://universal-api.panewslab.com"
POLYMARKET_API = "https://polymarket-boards.panewslab.com/api/boards"

DEFAULT_TIMEOUT = 15  # seconds


class PanewsClient:
    """Thin HTTP wrapper around the PANews universal API + Polymarket boards."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                "PA-Accept-Language": "zh",
            },
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Articles
    # ------------------------------------------------------------------

    def search_articles(
        self,
        query: str,
        *,
        mode: str = "hit",  # "hit" (relevance) | "time" (newest)
        take: int = 5,
        lang: str = "zh",
    ) -> dict[str, Any]:
        """Search PANews articles by keyword."""
        resp = self._post(
            "/search/articles",
            json={
                "query": query,
                "mode": mode,
                "type": ["NORMAL", "NEWS"],
                "take": min(take, 50),
                "skip": 0,
            },
        )
        articles = [item.get("article", {}) for item in (resp or [])]
        return {"success": True, "query": query, "count": len(articles), "articles": articles}

    def get_daily_must_reads(self, *, date: str = "", lang: str = "zh") -> dict[str, Any]:
        """Get today's (or a specific date's) daily must-read articles."""
        from datetime import date as _date

        target = date or _date.today().isoformat()
        resp = self._get(f"/daily-must-reads?date={target}")
        articles = [item.get("article", {}) for item in (resp or [])]
        return {"success": True, "date": target, "count": len(articles), "articles": articles}

    def get_rankings(
        self,
        *,
        ranking_type: str = "daily",  # "daily" (24h hot) | "weekly" (7-day search trending)
        take: int = 10,
        lang: str = "zh",
    ) -> dict[str, Any]:
        """Get article hot rankings."""
        path = f"/rankings/{ranking_type}?take={take}"
        resp = self._get(path)
        return {"success": True, "type": ranking_type, "articles": resp or []}

    def get_article(self, article_id: str, *, lang: str = "zh") -> dict[str, Any]:
        """Get full article content by ID."""
        resp = self._get(f"/articles/{article_id}")
        if not resp:
            return {"success": False, "error": "article not found", "article_id": article_id}
        return {"success": True, "article": resp}

    def list_articles(
        self,
        *,
        article_type: str = "",
        take: int = 10,
        lang: str = "zh",
    ) -> dict[str, Any]:
        """List latest articles, optionally filtered by type."""
        params = f"take={take}"
        if article_type:
            params += f"&type={article_type}"
        resp = self._get(f"/articles?{params}")
        return {"success": True, "count": len(resp or []), "articles": resp or []}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_hooks(self, *, category: str = "", lang: str = "zh") -> dict[str, Any]:
        """Get platform picks: hot searches, editor's picks, etc.

        Categories: "search-keywords" | "hot-articles" | …
        """
        params = f"category={category}" if category else ""
        resp = self._get(f"/hooks?{params}")
        return {"success": True, "category": category or "all", "items": resp or []}

    def list_columns(self, *, keyword: str = "", take: int = 10, lang: str = "zh") -> dict[str, Any]:
        """List or search PANews columns."""
        params = f"take={take}"
        if keyword:
            params += f"&keyword={keyword}"
        resp = self._get(f"/columns?{params}")
        return {"success": True, "count": len(resp or []), "columns": resp or []}

    def list_events(self, *, take: int = 10, lang: str = "zh") -> dict[str, Any]:
        """List PANews events/activities."""
        resp = self._get(f"/events?take={take}")
        return {"success": True, "count": len(resp or []), "events": resp or []}

    def list_calendar_events(
        self,
        *,
        date: str = "",
        category_id: str = "",
        lang: str = "zh",
    ) -> dict[str, Any]:
        """List calendar events for a date or category."""
        params = []
        if date:
            params.append(f"date={date}")
        if category_id:
            params.append(f"categoryId={category_id}")
        resp = self._get(f"/calendar/events?{'&'.join(params)}")
        return {"success": True, "count": len(resp or []), "events": resp or []}

    # ------------------------------------------------------------------
    # Polymarket smart money boards
    # ------------------------------------------------------------------

    def list_polymarket_boards(self) -> dict[str, Any]:
        """List newest Polymarket smart money board categories."""
        resp = self._polymarket_get("/categories")
        return {"success": True, "boards": resp or []}

    def get_polymarket_board(self, slug: str) -> dict[str, Any]:
        """Read latest entries for a specific smart money board."""
        resp = self._polymarket_get(f"/categories/{slug}")
        if not resp:
            return {"success": False, "error": "board not found", "slug": slug}
        return {"success": True, "board": resp}

    def get_polymarket_highlights(self) -> dict[str, Any]:
        """Summarize highlights from the newest smart money board run."""
        resp = self._polymarket_get("/highlights")
        return {"success": True, "highlights": resp or {}}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> Any:
        try:
            r = self._client.get(f"{UNIVERSAL_API}{path}")
            r.raise_for_status()
            return r.json()
        except Exception:
            logger.debug("PANews GET %s failed", path, exc_info=True)
            return None

    def _post(self, path: str, json: dict[str, Any]) -> Any:
        try:
            r = self._client.post(f"{UNIVERSAL_API}{path}", json=json)
            r.raise_for_status()
            return r.json()
        except Exception:
            logger.debug("PANews POST %s failed", path, exc_info=True)
            return None

    def _polymarket_get(self, path: str) -> Any:
        try:
            r = self._client.get(f"{POLYMARKET_API}{path}")
            r.raise_for_status()
            return r.json()
        except Exception:
            logger.debug("PANews Polymarket GET %s failed", path, exc_info=True)
            return None
