"""Domain models — frozen runtime snapshots injected into the agent prompt.

These types capture user identity, memory context, and policy state
at conversation creation time. They are never modified during a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserPersona:
    """Per-user prompt injection appended as ``# User Persona``.

    Holds a free-form ``custom_prompt`` that shapes the agent's
    communication style, persona, and behavioral defaults.
    """

    custom_prompt: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.custom_prompt.strip()


@dataclass(frozen=True)
class SessionOverrides:
    """Per-session prompt override appended as ``# Session Overrides``.

    Allows the caller to inject session-scoped instructions without
    modifying the persistent user persona.
    """

    custom_prompt: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.custom_prompt.strip()


@dataclass(frozen=True)
class MemorySnapshot:
    """Cross-session memory injected into the system prompt.

    ``summary_text`` is a human-readable paragraph; ``items`` is a
    structured list of facts (e.g. ``["last_query_NVDA fwd_pe=16.67"]``).
    """

    summary_text: str = ""
    items: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.summary_text.strip() and not self.items


@dataclass(frozen=True)
class PolicyView:
    """The allow-list of capability IDs for this conversation run.

    An empty list means "use the default-enabled set from the registry."
    """

    allowed_capability_ids: list[str] = field(default_factory=list)
