"""Tool dispatcher — dispatches tool requests to registered handlers.

The dispatcher sits between the runtime and the registry. When the agent
requests a tool call, the runtime builds a ``ToolRequest`` and
hands it to ``execute()``. The dispatcher resolves the handler, runs the
optional guard check, and returns the result.

★★★ Provenance hook: every successful tool result is automatically
registered in the FactRegistry (if attached). This is the ONLY place
facts get registered — adapters never touch the registry directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cagent_os.plugins.contracts import ToolRequest, ToolResult
from cagent_os.plugins.policy import ToolGuard
from cagent_os.plugins.registry import ToolRegistry

if TYPE_CHECKING:
    from cagent_os.provenance import FactRegistry

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """Resolve tool requests and delegate to the correct handler.

    Optionally enforces a ``ToolGuard`` (allow-list check) before
    invoking the handler.

    Args:
        registry: tool directory for handler resolution
        policy: optional guard for authorization
        fact_registry: optional FactRegistry for provenance tracking.
            If attached, every successful tool result is automatically
            decomposed into field-level facts.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: ToolGuard | None = None,
        fact_registry: FactRegistry | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._fact_registry = fact_registry

    @property
    def registry(self) -> ToolRegistry:
        """The tool directory used for handler resolution."""
        return self._registry

    @property
    def fact_registry(self) -> FactRegistry | None:
        return self._fact_registry

    def attach_fact_registry(self, registry: FactRegistry) -> None:
        """Attach or replace the fact registry (e.g., per turn)."""
        self._fact_registry = registry

    def execute(self, request: ToolRequest) -> ToolResult:
        """Authorise (if a guard is set) and dispatch a tool request.

        After execution, if a FactRegistry is attached and the result
        is successful, the result is automatically registered.
        """
        if self._policy is not None:
            self._policy.authorize(request.capability_id)
        handler = self._registry.resolve(request.capability_id)
        result = handler(request)

        # ★ Auto-register facts from successful tool results
        if self._fact_registry is not None:
            # Record the target ticker(s) of this tool call — used later
            # to detect tickers where ALL structured tools failed.
            # Read ALL ticker-like argument keys (different adapters use different names).
            args = request.arguments or {}
            for key in ("ticker", "symbols", "asset", "symbol"):
                val = args.get(key)
                if isinstance(val, str) and val.strip():
                    self._fact_registry.note_tool_target(val)
                elif isinstance(val, list):
                    for s in val:
                        if isinstance(s, str) and s.strip():
                            self._fact_registry.note_tool_target(s)

            if result.status == "ok":
                try:
                    registered = self._fact_registry.register_tool_result(
                        capability_id=request.capability_id,
                        result=result,
                        arguments=request.arguments,
                    )
                    if registered:
                        logger.debug(
                            "Registered %d facts from %s",
                            len(registered), request.capability_id,
                        )
                except Exception:
                    # Provenance must never break tool execution
                    logger.exception(
                        "Fact registration failed for %s — continuing",
                        request.capability_id,
                    )
            elif result.status == "error" and isinstance(result.content, dict):
                # ★ Detect out-of-coverage signals for routing-aware gate feedback.
                # When a tool returns "unavailable: true" (structural, not transient),
                # mark the registry so the gate knows this isn't a "go find data"
                # situation — it's a "data does not exist" situation.
                content = result.content
                if content.get("unavailable") and content.get("reason") == "institutional":
                    ticker = request.arguments.get("ticker", "") if request.arguments else ""
                    if ticker:
                        self._fact_registry.mark_out_of_coverage(
                            ticker, content.get("error", "unknown"),
                        )
                        logger.info(
                            "Out-of-coverage: %s (%s)", ticker, content.get("error"),
                        )

        return result
