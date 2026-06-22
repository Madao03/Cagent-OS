"""Conversation domain model — events, records, and projections.

Every user interaction, agent response, and tool invocation is captured
as an immutable ``JournalEntry``. The event stream is the single
source of truth (Event Sourcing) — the projector rebuilds the LLM
transcript from events on each turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cagent_os.domain.models import (
    MemorySnapshot,
    PolicyView,
    SessionOverrides,
    UserPersona,
)
from cagent_os.llm.protocol import ChatMessage, ToolCall
from cagent_os.user_skills.models import UserSkillSnapshot


@dataclass(frozen=True)
class JournalEntry:
    """A single immutable event in a conversation's lifecycle.

    Event types (``type`` field):
    - ``"message.user_added"`` — user sent input
    - ``"message.assistant_added"`` — agent produced text
    - ``"message.assistant_delta"`` — streaming text chunk
    - ``"message.assistant_tool_calls_added"`` — agent requested tools
    - ``"run.tool_requested"`` — tool execution started
    - ``"run.tool_completed"`` — tool execution finished
    - ``"run.tool_failed"`` — tool execution errored
    - ``"run.completed"`` / ``"run.failed"`` — run lifecycle end
    """

    type: str
    role: str | None = None
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionSnapshot:
    """A frozen snapshot captured at conversation creation time.

    Immutable — once created, the snapshot never changes. This ensures
    the agent operates against a consistent view of user skills, memory,
    and policy for the entire run.
    """

    conversation_id: str
    principal_id: str
    user_id: str
    user_skill_snapshot: UserSkillSnapshot
    policy_snapshot: PolicyView = field(default_factory=PolicyView)
    user_prompt_preferences_snapshot: UserPersona = field(default_factory=UserPersona)
    session_prompt_overrides: SessionOverrides = field(default_factory=SessionOverrides)
    memory_context: MemorySnapshot = field(default_factory=MemorySnapshot)


@dataclass(frozen=True)
class TranscriptView:
    """The LLM-compatible transcript rebuilt from the event stream."""

    transcript: list[ChatMessage]


# ------------------------------------------------------------------


def user_message(content: str) -> JournalEntry:
    """Create a ``user_added`` event from raw input text."""
    return JournalEntry(type="message.user_added", role="user", content=content)


def assistant_message(content: str) -> JournalEntry:
    """Create an ``assistant_added`` event for the final agent response."""
    return JournalEntry(type="message.assistant_added", role="assistant", content=content)


def assistant_tool_calls(content: str, tool_calls: list[ToolCall]) -> JournalEntry:
    """Create a ``tool_calls_added`` event capturing planned tool invocations."""
    return JournalEntry(
        type="message.assistant_tool_calls_added",
        role="assistant",
        content=content,
        data={
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": dict(tool_call.arguments),
                }
                for tool_call in tool_calls
            ]
        },
    )
