"""Conversation projector — rebuilds an LLM transcript from the event stream.

The projector is the "read" side of Event Sourcing. It walks the raw
``JournalEntry`` list in order and assembles the exact ``ChatMessage``
sequence that the LLM needs for its next call.
"""

from __future__ import annotations

import json

from cagent_os.conversations.models import JournalEntry, TranscriptView
from cagent_os.llm.protocol import ChatMessage, ToolCall


class TranscriptReplayer:
    """Replay the event stream into a linear LLM transcript.

    The projection rules:
    1. User and assistant text messages pass through directly.
    2. Tool-call events are resolved against actual execution results
       (only completed or failed tool calls appear in the transcript).
    3. Failed tool calls are serialized as structured JSON so the LLM
       can reason about what went wrong.
    """

    def project(self, events: list[JournalEntry]) -> TranscriptView:
        """Build a ``TranscriptView`` from an ordered event list."""

        # Collect all resolved tool-call IDs for filtering
        completed_ids = {
            str(e.data.get("tool_call_id", ""))
            for e in events
            if e.type == "run.tool_completed" and str(e.data.get("status", "ok")) == "ok"
        }
        failed_ids = {
            str(e.data.get("tool_call_id", ""))
            for e in events
            if e.type == "run.tool_failed"
        }
        resolved = completed_ids | failed_ids

        transcript: list[ChatMessage] = []
        assistant_tool_ids: set[str] = set()
        idx = 0

        while idx < len(events):
            ev = events[idx]

            # -- User / assistant text -------------------------------------------------
            if ev.type in {"message.user_added", "message.assistant_added"} and ev.role is not None:
                transcript.append(ChatMessage(role=ev.role, content=ev.content))
                idx += 1
                continue

            # -- Assistant planned tool calls ------------------------------------------
            if ev.type == "message.assistant_tool_calls_added" and ev.role is not None:
                raw = self._parse_tool_calls(ev.data.get("tool_calls"))
                raw_ids = {tc.id for tc in raw}
                # If any of the planned calls were actually executed, keep only those
                if raw_ids & resolved:
                    tool_calls = [tc for tc in raw if tc.id in resolved]
                else:
                    tool_calls = raw
                if not tool_calls:
                    idx += 1
                    continue
                assistant_tool_ids.update(tc.id for tc in tool_calls if tc.id)
                transcript.append(ChatMessage(role=ev.role, content=ev.content, tool_calls=tool_calls))
                idx += 1
                continue

            # -- Tool completed successfully -------------------------------------------
            if ev.type == "run.tool_completed":
                if str(ev.data.get("status", "ok")) != "ok":
                    idx += 1
                    continue
                call_id = str(ev.data.get("tool_call_id", "")) or None
                if call_id is not None and call_id not in assistant_tool_ids:
                    idx += 1
                    continue
                transcript.append(ChatMessage(
                    role="tool",
                    content=self._serialize_content(ev.data.get("result")),
                    tool_call_id=call_id,
                ))
                idx += 1
                continue

            # -- Tool failed -----------------------------------------------------------
            if ev.type == "run.tool_failed":
                call_id = str(ev.data.get("tool_call_id", "")) or None
                if call_id is not None and call_id not in assistant_tool_ids:
                    idx += 1
                    continue
                transcript.append(ChatMessage(
                    role="tool",
                    content=self._format_tool_failure(ev.data),
                    tool_call_id=call_id,
                ))
                idx += 1
                continue

            idx += 1

        return TranscriptView(transcript=transcript)

    # -- serialization helpers ----------------------------------------------------

    @staticmethod
    def _serialize_content(value: object) -> str:
        """Convert a tool result to a string suitable for the LLM transcript."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @classmethod
    def _format_tool_failure(cls, data: dict[str, object]) -> str:
        """Build a structured error message from a failed tool execution."""
        result = data.get("result")
        if result is not None:
            return cls._serialize_content(result)
        return cls._serialize_content({
            "success": False,
            "error": data.get("error_code") or "tool_failed",
            "message": data.get("message") or "",
            "details": data.get("details"),
        })

    @staticmethod
    def _parse_tool_calls(payload: object) -> list[ToolCall]:
        """Deserialize a raw tool-calls list from event data."""
        if not isinstance(payload, list):
            return []
        calls: list[ToolCall] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            args = item.get("arguments", {})
            if not isinstance(args, dict):
                args = {}
            calls.append(ToolCall(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                arguments=dict(args),
            ))
        return calls
