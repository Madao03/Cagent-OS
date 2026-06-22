"""LLM protocol types — provider-agnostic abstractions for model interaction.

All types in this module are OpenAI-compatible by default (the de facto
industry standard). The ``to_openai()`` methods produce dicts suitable for
any OpenAI-compatible HTTP API.

The system never calls provider APIs directly — it always goes through
these protocol types, which the backend adapters translate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


# ------------------------------------------------------------------
# Tool definitions
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSchema:
    """Schema for a tool the agent can call.

    Follows the OpenAI function-calling convention.
    """

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolCall:
    """A concrete tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


# ------------------------------------------------------------------
# Messages
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ChatMessage:
    """A single turn in the conversation transcript.

    Represents user input, assistant output, or tool result feedback.
    """

    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    # -- serialization --------------------------------------------------

    def to_openai(self) -> dict[str, Any]:
        """Produce an OpenAI-compatible dict for HTTP request bodies."""
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            payload["tool_calls"] = [tc.to_openai() for tc in self.tool_calls]
        return payload

    to_history = to_openai  # historical alias — keep for backward compat

    @classmethod
    def from_history(cls, payload: dict[str, Any]) -> "ChatMessage":
        """Hydrate an ``ChatMessage`` from a persisted history dict."""
        tool_calls: list[ToolCall] = []
        for item in payload.get("tool_calls", []):
            fn = item.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {}
            tool_calls.append(ToolCall(
                id=item.get("id", ""),
                name=fn.get("name", ""),
                arguments=args,
            ))
        return cls(
            role=payload["role"],
            content=payload.get("content", "") or "",
            tool_call_id=payload.get("tool_call_id"),
            tool_calls=tool_calls,
        )


ChatMessage = ChatMessage  # convenience alias


# ------------------------------------------------------------------
# Request / Response
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ReasoningOptions:
    """Controls reasoning-effort behavior for models that support it."""

    effort: str = "medium"
    include_reasoning: bool = False


@dataclass(frozen=True)
class InferenceOptions:
    """Provider-neutral knobs for LLM inference."""

    max_tokens: int = 32000
    temperature: float | None = None
    reasoning: ReasoningOptions | None = None
    response_format: dict[str, Any] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None


@dataclass(frozen=True)
class ModelRequest:
    """A complete request to be dispatched to an LLM provider."""

    model: str
    messages: list[ChatMessage]
    tools: list[ToolSchema] = field(default_factory=list)
    options: InferenceOptions = field(default_factory=InferenceOptions)


@dataclass(frozen=True)
class ModelResponse:
    """The provider's response after inference."""

    message: ChatMessage
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    raw: Any = None


@dataclass(frozen=True)
class StreamChunk:
    """A streaming delta event emitted during token-by-token generation."""

    type: str
    text: str | None = None
    tool_call: ToolCall | None = None
    finish_reason: str | None = None
