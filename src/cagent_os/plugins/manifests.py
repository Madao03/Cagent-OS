"""Plugin manifests — static declarations of what capabilities a plugin provides.

Every plugin must return a ``PluginSpec`` describing its capabilities,
their trust levels, and parameter schemas. The registry uses these manifests
to build the agent's allowed-capability list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cagent_os.plugins.contracts import ToolTrustLevel


@dataclass(frozen=True)
class ToolSpec:
    """Static metadata for a single capability.

    Attributes:
        capability_id: globally-unique identifier (e.g. ``"web.fetch_weixin"``)
        trust_level:   which security boundary the capability requires
        description:   human-readable summary shown to the agent
        parameters:    JSON Schema describing the expected arguments
    """

    capability_id: str
    trust_level: ToolTrustLevel
    description: str = ""
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


@dataclass(frozen=True)
class PluginSpec:
    """Static declaration of a plugin and its capabilities.

    Attributes:
        plugin_id:      unique plugin name (e.g. ``"financial"``, ``"web"``)
        capabilities:   one manifest per capability the plugin exposes
        default_enabled: whether capabilities are enabled by default
    """

    plugin_id: str
    capabilities: list[ToolSpec] = field(default_factory=list)
    default_enabled: bool = True
