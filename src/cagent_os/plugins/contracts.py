"""Capability contracts — immutable request/result types for tool execution.

This module defines the core data types that flow between an AI agent
and every registered capability (financial, web, file I/O, etc.).

All types are frozen dataclasses — they are immutable value objects
that carry data through the system without side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ToolTrustLevel(StrEnum):
    """Security boundary for a capability.

    Controls what resources the capability can access:
    - SAFE:       read-only, no network, no filesystem (memory queries, math)
    - NETWORKED:  outbound HTTP requests (web fetch, API calls)
    - FILESYSTEM: local disk read/write (document reader, write.file)
    - PRIVILEGED: system-level operations (process execution — disabled on Windows)
    """

    SAFE = "safe"
    NETWORKED = "networked"
    FILESYSTEM = "filesystem"
    PRIVILEGED = "privileged"


@dataclass(frozen=True)
class ToolRequest:
    """An immutable request dispatched to a registered capability.

    Attributes:
        capability_id: e.g. ``"financial.quote.verified"`` or ``"web.fetch"``
        arguments:     tool-specific key/value payload
        context:       optional metadata (user_id, conversation_id, etc.)
    """

    capability_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """The outcome of a single capability execution.

    ``status`` is ``"ok"`` for success or ``"error"`` for failure.
    On error, ``error_code`` carries a stable machine-readable label
    (e.g. ``"finance_empty_result"``, ``"web_fetch_failed"``).
    """

    status: str
    content: Any = None
    error_code: str | None = None
