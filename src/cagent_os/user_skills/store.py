from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from .models import UserSkillDocument


class UserSkillStore(ABC):
    @abstractmethod
    def load_user_skills(self, user_id: str) -> Sequence[UserSkillDocument]:
        """Return markdown-based documents for the given user, sorted deterministically."""

    @abstractmethod
    def save_user_skill(self, user_id: str, skill_name: str, content: str) -> UserSkillDocument:
        """Create or overwrite one markdown skill document for the given user."""
