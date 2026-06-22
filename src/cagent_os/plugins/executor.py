"""Tool dispatcher — dispatches tool requests to registered handlers.

The dispatcher sits between the runtime and the registry. When the agent
requests a tool call, the runtime builds a ``ToolRequest`` and
hands it to ``execute()``. The dispatcher resolves the handler, runs the
optional guard check, and returns the result.
"""

from __future__ import annotations

from cagent_os.plugins.contracts import ToolRequest, ToolResult
from cagent_os.plugins.policy import ToolGuard
from cagent_os.plugins.registry import ToolRegistry


class ToolDispatcher:
    """Resolve tool requests and delegate to the correct handler.

    Optionally enforces a ``ToolGuard`` (allow-list check) before
    invoking the handler.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: ToolGuard | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy

    @property
    def registry(self) -> ToolRegistry:
        """The tool directory used for handler resolution."""
        return self._registry

    def execute(self, request: ToolRequest) -> ToolResult:
        """Authorise (if a guard is set) and dispatch a tool request."""
        if self._policy is not None:
            self._policy.authorize(request.capability_id)
        handler = self._registry.resolve(request.capability_id)
        return handler(request)
