from __future__ import annotations

from dataclasses import dataclass, field

from cagent_os.domain.models import (
    MemorySnapshot,
    SessionOverrides,
    UserPersona,
)
from cagent_os.user_skills.models import UserSkillSnapshot


@dataclass(frozen=True)
class AgentProfile:
    user_skill_snapshot: UserSkillSnapshot
    capability_descriptions: list[str] = field(default_factory=list)
    user_prompt_preferences: UserPersona = field(default_factory=UserPersona)
    session_prompt_overrides: SessionOverrides = field(default_factory=SessionOverrides)
    memory_context: MemorySnapshot = field(default_factory=MemorySnapshot)
