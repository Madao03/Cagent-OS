from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class UserSkillDocument:
    id: str
    name: str
    content: str
    description: str = ""


@dataclass(frozen=True)
class UserSkillPrompt:
    id: str
    title: str
    body: str
    document_id: str | None = None


@dataclass(frozen=True)
class UserSkillSnapshot:
    user_id: str
    documents: tuple[UserSkillDocument, ...] = ()

    @classmethod
    def from_documents(cls, user_id: str, documents: Iterable[UserSkillDocument]) -> "UserSkillSnapshot":
        return cls(user_id=user_id, documents=tuple(documents))

    def __len__(self) -> int:
        return len(self.documents)
