from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolContext:
    """Ephemeral context for a single tool invocation.

    Created when a tool call begins, discarded when it ends.
    """

    capability_id: str
    tool_call_id: str
    timeout_sec: int = 30
    metadata: dict[str, object] = field(default_factory=dict)
