"""Capability registry — the central directory of all tools the agent can invoke.

Every plugin registers its capabilities here at startup. The registry
then serves as the single source of truth for tool manifests, handler
resolution, and allow-list filtering.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import ToolSpec
from cagent_os.llm.protocol import ToolSchema

if TYPE_CHECKING:
    from cagent_os.plugins.plugin import Plugin


# ------------------------------------------------------------------


@dataclass(frozen=True)
class RegisteredTool:
    """An entry in the capability directory — manifest + handler bound together."""

    manifest: ToolSpec
    handler: Callable[[ToolRequest], ToolResult]
    default_enabled: bool = True


class ToolRegistry:
    """Thread-safe directory of all capabilities available to the agent.

    Plugins register their capabilities at startup via ``register_plugin()``.
    The AgentRuntime queries ``tool_schemas()`` and ``allowed()`` to build
    the system prompt, and ``resolve()`` at runtime to dispatch tool calls.
    """

    def __init__(self) -> None:
        self._entries: dict[str, RegisteredTool] = {}

    # -- registration ---------------------------------------------------

    def register(
        self,
        *,
        capability_id: str,
        handler: Callable[[ToolRequest], ToolResult],
        manifest: ToolSpec | None = None,
        default_enabled: bool = True,
    ) -> None:
        """Register a single capability with an optional custom manifest."""
        self._entries[capability_id] = RegisteredTool(
            manifest=manifest
            or ToolSpec(
                capability_id=capability_id,
                trust_level=ToolTrustLevel.SAFE,
            ),
            handler=handler,
            default_enabled=default_enabled,
        )

    def register_plugin(self, plugin: Plugin) -> None:
        """Register every capability declared by a plugin."""
        plugin_manifest = plugin.manifest()
        for cap_manifest in plugin_manifest.capabilities:
            self.register(
                capability_id=cap_manifest.capability_id,
                manifest=cap_manifest,
                default_enabled=plugin_manifest.default_enabled,
                handler=plugin.handler(cap_manifest.capability_id),
            )

    # -- lookup ---------------------------------------------------------

    def resolve(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        """Return the handler for a capability (raises KeyError if unknown)."""
        return self._entries[capability_id].handler

    def spec_for(self, capability_id: str) -> ToolSpec:
        """Return the manifest for a capability (raises KeyError if unknown)."""
        return self._entries[capability_id].manifest

    # -- agent-facing helpers -------------------------------------------

    def allowed(self, requested_capability_ids: Iterable[str]) -> list[str]:
        """Filter requested IDs to only those that are registered and enabled."""
        result: list[str] = []
        for cid in requested_capability_ids:
            entry = self._entries.get(cid)
            if entry is None or not entry.default_enabled:
                continue
            result.append(cid)
        return result

    def default_enabled_tool_ids(self) -> list[str]:
        """Return every capability ID that is enabled by default."""
        return [cid for cid, e in self._entries.items() if e.default_enabled]

    def describe_allowed(self, capability_ids: Iterable[str]) -> list[str]:
        """Build a human-readable description list for the system prompt."""
        descriptions: list[str] = []
        for cid in capability_ids:
            entry = self._entries.get(cid)
            if entry is None:
                continue
            desc = entry.manifest.description
            descriptions.append(f"{cid}: {desc}" if desc else cid)
        return descriptions

    def tool_schemas(self, capability_ids: Iterable[str]) -> list[ToolSchema]:
        """Build OpenAI-compatible tool schemas for the given capability IDs."""
        defs: list[ToolSchema] = []
        for cid in capability_ids:
            entry = self._entries.get(cid)
            if entry is None:
                continue
            defs.append(ToolSchema(
                name=cid,
                description=entry.manifest.description,
                parameters=entry.manifest.parameters,
            ))
        return defs
