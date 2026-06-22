from __future__ import annotations

from .models import UserSkillSnapshot
from .parsing import extract_skill_description
from .store import UserSkillStore


class UserSkillService:
    def __init__(self, store: UserSkillStore):
        self._store = store

    def load_snapshot(self, user_id: str) -> UserSkillSnapshot:
        documents = self._load_runtime_skills(user_id)
        return UserSkillSnapshot.from_documents(user_id, documents)

    def list_skills(self, user_id: str):
        return tuple(self._load_runtime_skills(user_id))

    def save_skill(self, user_id: str, skill_name: str, content: str):
        return self._store.save_user_skill(user_id, skill_name, content)

    def get_skill(self, user_id: str, skill_name: str):
        for document in self._load_runtime_skills(user_id):
            if document.name == skill_name:
                return document
        raise KeyError(f"skill not found: {skill_name}")

    def build_skill_document(self, user_id: str, skill_name: str, content: str):
        if hasattr(self._store, "_validate_user_id"):
            self._store._validate_user_id(user_id)
        if hasattr(self._store, "_validate_skill_name"):
            self._store._validate_skill_name(skill_name)
        from .models import UserSkillDocument

        return UserSkillDocument(
            id=f"{user_id}:{skill_name}.md",
            name=skill_name,
            content=content,
            description=extract_skill_description(content),
        )

    def _load_runtime_skills(self, user_id: str):
        if hasattr(self._store, "load_runtime_skills"):
            return self._store.load_runtime_skills(user_id)
        return self._store.load_user_skills(user_id)
