"""Tool guard — whitelist-based authorization for tool invocations.

The guard sits in front of every tool dispatch. When the LLM returns a
tool call, the runtime asks the guard to authorize the tool name before
forwarding the request to the handler. This prevents hallucinated tool
names from reaching the dispatcher and enforces per-agent scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from cagent_os.shared.errors import ToolAccessDenied


@dataclass(frozen=True)
class ToolGuard:
    """Immutable allow-list of tool names an agent may invoke.

    Attributes:
        allowed: the set of tool names permitted by this guard.
            An empty set means no tools are allowed.
    """
    allowed: set[str] = field(default_factory=set)

    def authorize(self, tool_name: str) -> None:
        """Check whether *tool_name* is permitted.

        Raises:
            ToolAccessDenied: if *tool_name* is not in ``self.allowed``.
        """
        if tool_name not in self.allowed:
            raise ToolAccessDenied(
                f"Tool '{tool_name}' is not in this agent's allow-list "
                f"(allowed: {sorted(self.allowed) or 'none'})."
            )

    def __repr__(self) -> str:
        return f"ToolGuard(allowed={sorted(self.allowed)})"
