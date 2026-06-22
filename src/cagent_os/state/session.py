from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionState:
    """Cross-agent shared state tied to one conversation.

    Only the Harness (orchestrator) writes to this. Agents read from it but
    must not modify it — their private state lives in AgentState.
    """

    user_id: str
    conversation_id: str
    metadata: dict[str, object] = field(default_factory=dict)
