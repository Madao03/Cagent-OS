"""Pydantic v2 state schemas — three-layer separation.

These exist alongside the lightweight dataclass versions in cagent_os.state.
The Pydantic versions add:
  - JSON serialization for trace/database storage
  - Validation on field types
  - Auto-generated JSON Schema for tool contracts
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class SessionStateSchema(BaseModel):
    """Cross-agent shared state tied to one conversation.

    Only the Harness writes to this. Agents read from it but must not modify.
    """

    user_id: str
    conversation_id: str
    principal_id: str = "default"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentStateSchema(BaseModel):
    """Private state scoped to a single agent execution.

    One agent cannot read another agent's state.
    Cross-agent communication uses structured Pydantic message schemas only.
    """

    agent_name: str
    agent_role: str = "researcher"
    skill_invocations: list[str] = Field(default_factory=list)  # skills loaded
    intermediate_reasoning: dict[str, Any] = Field(default_factory=dict)
    scratchpad: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class ToolContextSchema(BaseModel):
    """Ephemeral context for a single tool invocation.

    Created when a tool call begins, discarded when it ends.
    """

    capability_id: str
    tool_call_id: str
    agent_name: str = ""
    timeout_sec: int = 30
    retry_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
