"""Runtime error types for the agent system.

Each error class maps to a stable ErrorCode string for logging and
observability. All inherit from RuntimeErrorBase so callers can catch
the whole family with a single except clause.
"""
from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable machine-readable error identifiers."""
    TOOL_ACCESS_DENIED = "tool_access_denied"
    CONVERSATION_OWNERSHIP = "conversation_ownership"


class RuntimeErrorBase(Exception):
    """Base type for all recoverable runtime errors."""
    code: ErrorCode

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class ToolAccessDenied(RuntimeErrorBase):
    """Raised when a tool name is not in the agent's allow-list.

    This guards against LLM-hallucinated tool names and prevents
    an agent from invoking tools outside its granted scope.
    """
    code = ErrorCode.TOOL_ACCESS_DENIED


class ConversationOwnershipError(RuntimeErrorBase):
    """Raised when a principal tries to access a conversation they don't own."""
    code = ErrorCode.CONVERSATION_OWNERSHIP
