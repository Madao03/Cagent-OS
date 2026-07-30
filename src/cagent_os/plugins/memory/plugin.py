"""Memory plugin — LLM tools for Hermes-style markdown memory.

Tools exposed:
  - memory.get_full_state:  Read both agent_notes + user_profile + char usage
  - memory.update_notes:    Replace agent_notes body (with char cap)
  - memory.update_profile:  Replace user_profile body (with char cap)

The LLM uses these to remember user preferences, project context, and
past conclusions across sessions. Char caps force consolidation rather
than hoarding (Hermes design).
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from cagent_os.memory.sqlite_store import (
    AGENT_NOTES_CHAR_LIMIT,
    MemoryOverflow,
    SqliteMemoryStore,
    USER_PROFILE_CHAR_LIMIT,
)
from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import PluginSpec, ToolSpec
from cagent_os.plugins.plugin import Plugin

logger = logging.getLogger(__name__)


class MemoryPlugin(Plugin):
    """LLM tools for reading/writing the two markdown memory files.

    user_id is passed at execution time via ToolRequest.context — set by
    run_engine based on conversation.user_id (which equals principal_id
    after the Phase A isolation fix).
    """

    def __init__(self, memory_store: SqliteMemoryStore) -> None:
        self._store = memory_store

    def manifest(self) -> PluginSpec:
        return PluginSpec(
            plugin_id="memory",
            default_enabled=True,
            capabilities=[
                ToolSpec(
                    capability_id="memory.get_full_state",
                    trust_level=ToolTrustLevel.SAFE,
                    description=(
                        "Read the user's full memory state: agent_notes (your running notes "
                        "about this user, the project, environment quirks) and user_profile "
                        "(the user's preferences, communication style, investment style). "
                        "Call this BEFORE updating memory to see what's already there. "
                        "Returns both files' content + character usage."
                    ),
                    parameters={"type": "object", "properties": {}, "required": []},
                ),
                ToolSpec(
                    capability_id="memory.update_notes",
                    trust_level=ToolTrustLevel.SAFE,
                    description=(
                        "REPLACE the entire agent_notes body. Use for notes about the user, "
                        "the project, environment facts, tool gotchas — things YOU (the agent) "
                        "want to remember for next time. Max 2000 chars; if exceeded, you'll "
                        "get the current content back — consolidate (merge/dedupe) and retry. "
                        "Use markdown sections (##) and bullets for readability."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "body": {
                                "type": "string",
                                "description": "The full new content of agent_notes (markdown).",
                            },
                        },
                        "required": ["body"],
                    },
                ),
                ToolSpec(
                    capability_id="memory.update_profile",
                    trust_level=ToolTrustLevel.SAFE,
                    description=(
                        "REPLACE the entire user_profile body. Use for the USER's preferences: "
                        "language, communication style, investment horizon, risk tolerance, "
                        "favorite sectors, etc. Max 1500 chars; consolidate on overflow."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "body": {
                                "type": "string",
                                "description": "The full new content of user_profile (markdown).",
                            },
                        },
                        "required": ["body"],
                    },
                ),
            ],
        )

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        if capability_id not in (
            "memory.get_full_state",
            "memory.update_notes",
            "memory.update_profile",
        ):
            raise KeyError(capability_id)
        return lambda request: self._sync_execute(capability_id, request)

    def _sync_execute(self, capability_id: str, request: ToolRequest) -> ToolResult:
        """Sync wrapper around async memory store methods.

        Uses a fresh event loop because ToolDispatcher runs handlers in a
        synchronous context (thread pool). The memory store's connection
        was opened on the main async loop; using a separate loop here is
        safe because aiosqlite spawns its own thread for the connection.
        """
        import asyncio

        user_id = request.context.get("user_id") if request.context else None
        if not user_id:
            return ToolResult(
                status="error",
                content={"error": "user_id missing from tool context"},
                error_code="missing_user_id",
            )

        async def _run():
            try:
                if capability_id == "memory.get_full_state":
                    notes = await self._store.get_agent_notes(user_id)
                    profile = await self._store.get_user_profile(user_id)
                    return {
                        "agent_notes": {
                            "body": notes.body,
                            "chars_used": notes.chars_used,
                            "char_limit": notes.char_limit,
                            "remaining": notes.remaining,
                        },
                        "user_profile": {
                            "body": profile.body,
                            "chars_used": profile.chars_used,
                            "char_limit": profile.char_limit,
                            "remaining": profile.remaining,
                        },
                    }
                elif capability_id == "memory.update_notes":
                    body = request.arguments.get("body", "")
                    try:
                        mem = await self._store.update_agent_notes(user_id, body)
                        return {
                            "status": "updated",
                            "chars_used": mem.chars_used,
                            "char_limit": mem.char_limit,
                            "remaining": mem.remaining,
                        }
                    except MemoryOverflow as exc:
                        # Hermes pattern: return current state + consolidation hint
                        return {
                            "status": "overflow",
                            "error": "agent_notes exceeds 2000 char limit",
                            "current_body": exc.current_body,
                            "attempted_chars": len(exc.attempted_body),
                            "char_limit": exc.char_limit,
                            "hint": "Consolidate current_body (merge overlapping entries, "
                                    "drop stale ones), then call update_notes again.",
                        }
                elif capability_id == "memory.update_profile":
                    body = request.arguments.get("body", "")
                    try:
                        mem = await self._store.update_user_profile(user_id, body)
                        return {
                            "status": "updated",
                            "chars_used": mem.chars_used,
                            "char_limit": mem.char_limit,
                            "remaining": mem.remaining,
                        }
                    except MemoryOverflow as exc:
                        return {
                            "status": "overflow",
                            "error": "user_profile exceeds 1500 char limit",
                            "current_body": exc.current_body,
                            "attempted_chars": len(exc.attempted_body),
                            "char_limit": exc.char_limit,
                            "hint": "Consolidate current_body, then retry.",
                        }
            except Exception as exc:
                logger.exception("memory tool failed: %s", exc)
                return {"error": str(exc)}
            return {"error": f"unknown capability: {capability_id}"}

        try:
            loop = asyncio.new_event_loop()
            try:
                content = loop.run_until_complete(_run())
            finally:
                loop.close()
        except RuntimeError:
            # Fallback: if there's already a running loop, use a thread
            import threading
            result_box = []
            def _runner():
                result_box.append(asyncio.run(_run()))
            t = threading.Thread(target=_runner)
            t.start()
            t.join()
            content = result_box[0]

        # ToolResult has 3 fields: status, content, error_code
        # "overflow" is a soft success — LLM should see the hint and react
        if isinstance(content, dict) and content.get("status") == "overflow":
            return ToolResult(status="ok", content=content)
        if isinstance(content, dict) and "error" in content:
            return ToolResult(status="error", content=content, error_code="memory_error")
        return ToolResult(status="ok", content=content)
