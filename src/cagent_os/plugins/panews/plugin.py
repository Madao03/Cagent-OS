"""PANews plugin — crypto news, market narratives & Polymarket smart money.

Registers seven capabilities (search, briefing, trending, article,
polymarket, hooks, events). All read endpoints are public — no API key required.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import ToolSpec, PluginSpec
from cagent_os.plugins.plugin import Plugin
from cagent_os.plugins.panews.client import PanewsClient

logger = logging.getLogger(__name__)

KNOWN_PANEWS_ERROR_CODES = {
    "panews_search_failed",
    "panews_briefing_failed",
    "panews_trending_failed",
    "panews_article_failed",
    "panews_polymarket_failed",
    "panews_hooks_failed",
    "panews_events_failed",
    "invalid_args",
}


class PanewsPlugin(Plugin):
    def __init__(self) -> None:
        self._client: PanewsClient | None = None

    @property
    def client(self) -> PanewsClient:
        if self._client is None:
            self._client = PanewsClient()
        return self._client

    def manifest(self) -> PluginSpec:
        return PluginSpec(
            plugin_id="panews",
            capabilities=[
                self._manifest(
                    "panews.search",
                    "Search PANews crypto/blockchain articles by keyword. "
                    "Returns title, summary, publish time, and article ID for each result. "
                    "Use this for Chinese crypto news discovery — covers project updates, "
                    "market narratives, regulatory news, and industry events.",
                    {
                        "query": {"type": "string", "description": "Search keyword"},
                        "mode": {"type": "string", "default": "hit", "description": "hit (relevance) or time (newest first)"},
                        "take": {"type": "integer", "default": 5, "description": "Number of results (max 50)"},
                        "lang": {"type": "string", "default": "zh", "description": "Language: zh, en, zh-TW"},
                    },
                    required=["query"],
                ),
                self._manifest(
                    "panews.briefing",
                    "Get today's daily must-read articles from PANews editors. "
                    "Best entry point for 'what's happening in crypto today?' — "
                    "curated top stories with summaries.",
                    {
                        "date": {"type": "string", "default": "", "description": "Date in YYYY-MM-DD (default: today)"},
                        "lang": {"type": "string", "default": "zh"},
                    },
                ),
                self._manifest(
                    "panews.trending",
                    "Get article hot rankings from PANews. "
                    "daily = 24h hot list. weekly = 7-day search trending. "
                    "Use to discover what the Chinese crypto community is paying attention to.",
                    {
                        "ranking_type": {"type": "string", "default": "daily", "description": "daily or weekly"},
                        "take": {"type": "integer", "default": 10},
                    },
                ),
                self._manifest(
                    "panews.article",
                    "Get full article content by PANews article ID. "
                    "Use after search or briefing to deep-dive into a specific article.",
                    {
                        "article_id": {"type": "string", "description": "PANews article ID from search/briefing/trending results"},
                    },
                    required=["article_id"],
                ),
                self._manifest(
                    "panews.polymarket",
                    "Access Polymarket smart money leaderboard data. "
                    "Available actions: boards (list categories), board (get specific board by slug), "
                    "highlights (latest cycle changes). "
                    "Use for tracking smart money positioning on prediction markets.",
                    {
                        "action": {"type": "string", "description": "boards | board | highlights"},
                        "slug": {"type": "string", "default": "", "description": "Board slug (required for action=board)"},
                    },
                    required=["action"],
                ),
                self._manifest(
                    "panews.hooks",
                    "Get PANews platform picks: hot search keywords, editor's picks, etc. "
                    "Use to discover trending topics and what the community is searching for.",
                    {
                        "category": {"type": "string", "default": "search-keywords", "description": "search-keywords | hot-articles | …"},
                    },
                ),
                self._manifest(
                    "panews.events",
                    "List upcoming crypto industry events, conferences, hackathons, and activities "
                    "from the PANews event calendar.",
                    {
                        "take": {"type": "integer", "default": 10},
                    },
                ),
            ],
        )

    # ------------------------------------------------------------------
    # Plugin interface
    # ------------------------------------------------------------------

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        known_capabilities = {m.capability_id for m in self.manifest().capabilities}
        if capability_id not in known_capabilities:
            raise KeyError(capability_id)

        def _handler(request: ToolRequest) -> ToolResult:
            try:
                result = self._dispatch(capability_id, request)
                return ToolResult(status="ok", content=result)
            except Exception as exc:
                logger.warning("PANews handler failed: %s — %s", capability_id, exc)
                return ToolResult(
                    status="error",
                    error_code=self._normalize_error_code(str(exc)),
                    content={"success": False, "error": str(exc)},
                )

        return _handler

    def _dispatch(self, capability_id: str, request: ToolRequest) -> dict[str, Any]:
        args = request.arguments
        if capability_id == "panews.search":
            return self.client.search_articles(
                query=str(args.get("query", "")),
                mode=str(args.get("mode", "hit")),
                take=int(args.get("take", 5)),
                lang=str(args.get("lang", "zh")),
            )
        if capability_id == "panews.briefing":
            return self.client.get_daily_must_reads(
                date=str(args.get("date", "")),
                lang=str(args.get("lang", "zh")),
            )
        if capability_id == "panews.trending":
            return self.client.get_rankings(
                ranking_type=str(args.get("ranking_type", "daily")),
                take=int(args.get("take", 10)),
                lang=str(args.get("lang", "zh")),
            )
        if capability_id == "panews.article":
            return self.client.get_article(
                article_id=str(args.get("article_id", "")),
                lang=str(args.get("lang", "zh")),
            )
        if capability_id == "panews.polymarket":
            action = str(args.get("action", "boards"))
            if action == "boards":
                return self.client.list_polymarket_boards()
            if action == "board":
                slug = str(args.get("slug", ""))
                if not slug:
                    return {"success": False, "error": "invalid_args", "message": "slug is required for action=board"}
                return self.client.get_polymarket_board(slug)
            if action == "highlights":
                return self.client.get_polymarket_highlights()
            return {"success": False, "error": "invalid_args", "message": f"Unknown action: {action}"}
        if capability_id == "panews.hooks":
            return self.client.get_hooks(
                category=str(args.get("category", "search-keywords")),
                lang=str(args.get("lang", "zh")),
            )
        if capability_id == "panews.events":
            return self.client.list_events(
                take=int(args.get("take", 10)),
                lang=str(args.get("lang", "zh")),
            )
        raise KeyError(capability_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_error_code(raw: str) -> str:
        normalized = raw.strip() or "panews_provider_error"
        if normalized in KNOWN_PANEWS_ERROR_CODES:
            return normalized
        return "panews_provider_error"

    @staticmethod
    def _manifest(
        capability_id: str,
        description: str,
        properties: dict[str, Any],
        *,
        required: list[str] | None = None,
    ) -> ToolSpec:
        return ToolSpec(
            capability_id=capability_id,
            trust_level=ToolTrustLevel.NETWORKED,
            description=description,
            parameters={
                "type": "object",
                "properties": properties,
                **({"required": required} if required else {}),
            },
        )
