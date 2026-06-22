from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentState:
    """Private state scoped to a single agent execution.

    One agent cannot read another agent's AgentState — cross-agent
    communication happens through Pydantic message schemas only.
    """

    agent_name: str
    intermediate_reasoning: dict[str, object] = field(default_factory=dict)
    scratchpad: dict[str, object] = field(default_factory=dict)
